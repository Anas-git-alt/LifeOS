import { useEffect, useState } from "react";
import { getProfile, updateProfile } from "../api";

export default function ProfileSettings() {
  const [form, setForm] = useState(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    load();
  }, []);

  async function load() {
    try {
      const profile = await getProfile();
      setForm(profile);
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
        <p>Timezone, location, shift, and nudge preferences.</p>
      </header>
      {message && <div className="glass-card" style={{ marginBottom: 14 }}>{message}</div>}
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
        <button className="btn btn-primary" onClick={save}>
          Save
        </button>
      </div>
    </div>
  );
}

function Field({ label, value, onChange }) {
  return (
    <div className="form-group">
      <label>{label}</label>
      <input value={value || ""} onChange={(event) => onChange(event.target.value)} />
    </div>
  );
}
