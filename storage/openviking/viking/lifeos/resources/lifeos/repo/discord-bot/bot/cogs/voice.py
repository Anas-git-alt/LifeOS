"""Discord voice commands for local agent speech playback."""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import tempfile
from dataclasses import dataclass, field

import discord
from discord.ext import commands

from bot.utils import api_post


@dataclass
class GuildVoiceState:
    session_id: int
    agent_name: str
    voice_client: discord.VoiceClient
    queue: list[tuple[str, str]]
    queue_policy: str = "replace"
    worker_task: asyncio.Task | None = None
    stop_flag: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class VoiceCog(commands.Cog, name="Voice"):
    def __init__(self, bot):
        self.bot = bot
        self.states: dict[int, GuildVoiceState] = {}
        self.logger = logging.getLogger("lifeos-bot.voice")

    @staticmethod
    def _trim_error(exc: Exception, max_len: int = 220) -> str:
        return str(exc).strip()[:max_len]

    async def _ensure_joined(self, ctx, agent_name: str, channel: discord.VoiceChannel | None):
        if not ctx.guild:
            raise RuntimeError("Voice commands require a guild")
        guild_id = ctx.guild.id
        target_channel = channel
        if not target_channel:
            if not ctx.author.voice or not ctx.author.voice.channel:
                raise RuntimeError("Join a voice channel first or pass a target channel.")
            target_channel = ctx.author.voice.channel
        existing = self.states.get(guild_id)
        if existing and existing.voice_client and existing.voice_client.is_connected():
            if existing.voice_client.channel.id != target_channel.id:
                await existing.voice_client.move_to(target_channel)
            existing.agent_name = agent_name
            payload = await api_post(
                "/voice/sessions/start",
                {
                    "guild_id": str(ctx.guild.id),
                    "channel_id": str(target_channel.id),
                    "agent_name": agent_name,
                    "queue_policy": existing.queue_policy,
                },
            )
            existing.session_id = int(payload["session_id"])
            return existing

        try:
            voice_client = await target_channel.connect(self_deaf=True)
        except Exception as exc:
            raise RuntimeError(f"Discord voice connect failed: {self._trim_error(exc)}") from exc

        try:
            payload = await api_post(
                "/voice/sessions/start",
                {
                    "guild_id": str(ctx.guild.id),
                    "channel_id": str(target_channel.id),
                    "agent_name": agent_name,
                    "queue_policy": "replace",
                },
            )
        except Exception:
            if voice_client.is_connected():
                await voice_client.disconnect(force=True)
            raise
        state = GuildVoiceState(
            session_id=int(payload["session_id"]),
            agent_name=agent_name,
            voice_client=voice_client,
            queue=[],
            queue_policy="replace",
        )
        self.states[guild_id] = state
        state.worker_task = asyncio.create_task(self._worker_loop(ctx.guild.id), name=f"voice-worker-{ctx.guild.id}")
        return state

    async def _worker_loop(self, guild_id: int):
        while True:
            state = self.states.get(guild_id)
            if not state or state.stop_flag:
                return
            if not state.queue:
                await asyncio.sleep(0.1)
                continue
            _, text = state.queue.pop(0)
            try:
                synth = await api_post(
                    "/tts/synthesize",
                    {
                        "agent_name": state.agent_name,
                        "text": text,
                        "queue_policy": state.queue_policy,
                    },
                )
            except Exception:
                await asyncio.sleep(0.2)
                continue

            audio_b64 = synth.get("audio_b64_wav")
            if not audio_b64:
                continue
            raw = base64.b64decode(audio_b64)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
                tmp.write(raw)
                wav_path = tmp.name

            done = asyncio.Event()

            def _after_playback(err: Exception | None):
                try:
                    os.remove(wav_path)
                except OSError:
                    pass
                done.set()

            if not state.voice_client.is_connected():
                done.set()
            else:
                try:
                    source = discord.FFmpegOpusAudio(wav_path)
                    state.voice_client.play(source, after=_after_playback)
                except Exception as exc:
                    self.logger.error("Voice playback failed: %s", exc)
                    try:
                        os.remove(wav_path)
                    except OSError:
                        pass
                    done.set()
            await done.wait()

    async def _interrupt(self, guild_id: int, reason: str = "interrupt"):
        state = self.states.get(guild_id)
        if not state:
            return
        state.queue.clear()
        try:
            await api_post(f"/voice/sessions/{state.session_id}/interrupt", {"reason": reason})
        except Exception:
            pass
        if state.voice_client and state.voice_client.is_playing():
            state.voice_client.stop()

    @commands.command(name="joinvoice")
    async def join_voice(self, ctx, agent_name: str):
        try:
            state = await self._ensure_joined(ctx, agent_name, None)
            await ctx.send(
                embed=discord.Embed(
                    title="Voice session started",
                    description=f"Agent `{agent_name}` is ready in {state.voice_client.channel.mention}.",
                    color=0x16A34A,
                )
            )
        except Exception as exc:
            await ctx.send(f"Failed to join voice: {self._trim_error(exc)}")

    @commands.command(name="speak")
    async def speak_as_agent(self, ctx, agent_name: str, *, text: str):
        if not text.strip():
            await ctx.send("Provide text to speak.")
            return
        try:
            state = await self._ensure_joined(ctx, agent_name, None)
            async with state.lock:
                if state.queue_policy == "replace":
                    await self._interrupt(ctx.guild.id, reason="replace_queue")
                state.queue.append((agent_name, text.strip()))
                state.agent_name = agent_name
            await ctx.send(f"Queued speech for `{agent_name}`.")
        except Exception as exc:
            await ctx.send(f"Failed to queue speech: {self._trim_error(exc)}")

    @commands.command(name="interrupt")
    async def interrupt_voice(self, ctx):
        if not ctx.guild or ctx.guild.id not in self.states:
            await ctx.send("No active voice session.")
            return
        try:
            await self._interrupt(ctx.guild.id)
            await ctx.send("Interrupted current voice playback and cleared queue.")
        except Exception as exc:
            await ctx.send(f"Interrupt failed: {self._trim_error(exc)}")

    @commands.command(name="leavevoice")
    async def leave_voice(self, ctx):
        if not ctx.guild:
            await ctx.send("This command requires a guild.")
            return
        state = self.states.get(ctx.guild.id)
        if not state:
            await ctx.send("No active voice session.")
            return
        state.stop_flag = True
        await self._interrupt(ctx.guild.id, reason="session_stop")
        try:
            await api_post(f"/voice/sessions/{state.session_id}/stop", {"reason": "discord_leave"})
        except Exception:
            pass
        if state.voice_client and state.voice_client.is_connected():
            await state.voice_client.disconnect(force=True)
        if state.worker_task:
            state.worker_task.cancel()
        self.states.pop(ctx.guild.id, None)
        await ctx.send("Left voice channel and closed voice session.")


async def setup(bot):
    await bot.add_cog(VoiceCog(bot))
