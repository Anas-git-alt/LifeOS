import { useEffect, useState } from "react";
import { getProfile, updateProfile } from "../api";

export default function ProfileSettings() {
  const [form, setForm] = useState(null);
  const [message, setMessage] = useState("");
  const isSuccessMessage = message === "Profile saved.";

  useEffect(() => {
    load();
  }, []);

  async function load() {
    try {
      const profile = await getProfile();
      setForm({
        ...profile,
        sleep_wind_down_checklist_text: (profile.sleep_wind_down_checklist || []).join("\n"),
      });
      setMessage("");
    } catch (err) {
      setMessage(err.message);
    }
  }

  async function save() {
    try {
      await updateProfile({
        timezone: form.timezone,
        city: form.city,
        country: form.country,
        prayer_method: Number(form.prayer_method),
        work_shift_start: form.work_shift_start,
        work_shift_end: form.work_shift_end,
        quiet_hours_start: form.quiet_hours_start,
        quiet_hours_end: form.quiet_hours_end,
        nudge_mode: form.nudge_mode,
        sleep_bedtime_target: form.sleep_bedtime_target,
        sleep_wake_target: form.sleep_wake_target,
        sleep_caffeine_cutoff: form.sleep_caffeine_cutoff,
        sleep_wind_down_checklist: parseChecklist(form.sleep_wind_down_checklist_text),
      });
      setMessage("Profile saved.");
    } catch (err) {
      setMessage(err.message);
    }
  }

  if (!form) return <div className="glass-card">Loading profile...</div>;

  return (
    <div>
      <header className="page-header">
        <h1>Profile</h1>
        <p>Timezone, location, shift, nudge, and core sleep protocol preferences.</p>
      </header>
      {message && (
        <div className={`glass-card ${isSuccessMessage ? "status-message-success" : "status-message-error"}`} style={{ marginBottom: 14 }}>
          {message}
        </div>
      )}
      <div className="glass-card" style={{ maxWidth: 720 }}>
        <div className="grid grid-2">
          <Field label="Timezone" value={form.timezone} onChange={(value) => setForm({ ...form, timezone: value })} />
          <Field label="City" value={form.city} onChange={(value) => setForm({ ...form, city: value })} />
          <Field label="Country" value={form.country} onChange={(value) => setForm({ ...form, country: value })} />
          <Field
            label="Prayer Method"
            value={String(form.prayer_method)}
            onChange={(value) => setForm({ ...form, prayer_method: value })}
          />
          <Field
            label="Shift Start"
            value={form.work_shift_start}
            onChange={(value) => setForm({ ...form, work_shift_start: value })}
          />
          <Field
            label="Shift End"
            value={form.work_shift_end}
            onChange={(value) => setForm({ ...form, work_shift_end: value })}
          />
          <Field
            label="Quiet Start"
            value={form.quiet_hours_start}
            onChange={(value) => setForm({ ...form, quiet_hours_start: value })}
          />
          <Field
            label="Quiet End"
            value={form.quiet_hours_end}
            onChange={(value) => setForm({ ...form, quiet_hours_end: value })}
          />
          <div className="form-group">
            <label>Nudge Mode</label>
            <select value={form.nudge_mode} onChange={(event) => setForm({ ...form, nudge_mode: event.target.value })}>
              <option value="moderate">moderate</option>
              <option value="high">high</option>
              <option value="on_demand">on_demand</option>
            </select>
          </div>
        </div>
        <div className="panel-card-head" style={{ marginTop: 8 }}>
          <h2>Sleep Protocol</h2>
          <span>Targets shown on Today board</span>
        </div>
        <div className="grid grid-3">
          <TimeField
            label="Bedtime Target"
            value={form.sleep_bedtime_target}
            onChange={(value) => setForm({ ...form, sleep_bedtime_target: value })}
          />
          <TimeField
            label="Wake Target"
            value={form.sleep_wake_target}
            onChange={(value) => setForm({ ...form, sleep_wake_target: value })}
          />
          <TimeField
            label="Caffeine Cutoff"
            value={form.sleep_caffeine_cutoff}
            onChange={(value) => setForm({ ...form, sleep_caffeine_cutoff: value })}
          />
        </div>
        <div className="form-group" style={{ marginTop: 12 }}>
          <label htmlFor="sleep-wind-down-checklist">Wind-Down Checklist</label>
          <textarea
            id="sleep-wind-down-checklist"
            rows={5}
            value={form.sleep_wind_down_checklist_text || ""}
            onChange={(event) => setForm({ ...form, sleep_wind_down_checklist_text: event.target.value })}
            placeholder={"Dim lights and put phone away\nSet tomorrow's first step\nBrush teeth and make wudu"}
          />
        </div>
        <button className="btn btn-primary" onClick={save}>
          Save
        </button>
      </div>
    </div>
  );
}

function Field({ label, value, onChange }) {
  const id = `profile-${label.toLowerCase().replace(/\s+/g, "-")}`;
  return (
    <div className="form-group">
      <label htmlFor={id}>{label}</label>
      <input id={id} value={value || ""} onChange={(event) => onChange(event.target.value)} />
    </div>
  );
}

function TimeField({ label, value, onChange }) {
  const id = `profile-${label.toLowerCase().replace(/\s+/g, "-")}`;
  return (
    <div className="form-group">
      <label htmlFor={id}>{label}</label>
      <input id={id} type="time" value={value || ""} onChange={(event) => onChange(event.target.value)} />
    </div>
  );
}

function parseChecklist(raw) {
  return String(raw || "")
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}
