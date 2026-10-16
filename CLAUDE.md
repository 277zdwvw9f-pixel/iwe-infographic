# iwe-infographic

Public repository: the `/infographic` skill (`SKILL.md`) and its engine (`engine/`).

- Anyone can read this repository. Never commit client material, personal data, brand fonts or
  logos, built pages with real content, or secrets. Brand looks live in a local folder
  (`IG_BRAND_DIRS`, default `$IWE_WORKSPACE/DS-strategy/local/infographic-brands/`).
- Before a commit: `python3 -m unittest tests/test_infographic.py` (also under Python 3.9).
- SKILL.md refers to its own files through `${CLAUDE_SKILL_DIR}`; keep paths relative to it.
- The promise of the skill is `docs/service-clause.md`; change it together with the behaviour.
