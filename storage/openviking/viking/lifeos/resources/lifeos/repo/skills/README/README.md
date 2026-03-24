# LifeOS Skills

Versioned, testable AI skill modules that extend agent capabilities.

## Structure

Each skill is a self-contained module:

```
skills/
└── <skill_name>/
    ├── manifest.yaml     # Name, version, description, triggers, I/O
    ├── skill.py           # Implementation
    └── tests/
        └── test_<name>.py # Tests (required)
```

## Adding a New Skill

1. Create a branch: `git checkout -b skill/<name>`
2. Create directory: `skills/<name>/`
3. Add `manifest.yaml` with required fields: name, version, description
4. Implement in `skill.py`
5. Add tests in `tests/`
6. Push and open a PR — GitHub Actions will validate manifest + run tests
7. **User must approve and merge** — no auto-deploy

## SkillOps Policy

| Action | Allowed? |
|---|---|
| Open PR with new skill | ✅ Automated |
| Run tests on PR | ✅ Automated |
| Merge PR | ❌ Manual approval only |
| Deploy to production | ❌ Manual only |
| Modify existing skills | ✅ Via PR only |
| Delete skills | ❌ Manual only |
