ALTER TABLE user_profile ADD COLUMN sleep_bedtime_target VARCHAR(5) DEFAULT '23:30';
ALTER TABLE user_profile ADD COLUMN sleep_wake_target VARCHAR(5) DEFAULT '07:30';
ALTER TABLE user_profile ADD COLUMN sleep_caffeine_cutoff VARCHAR(5) DEFAULT '15:00';
ALTER TABLE user_profile ADD COLUMN sleep_wind_down_checklist_json JSON;
