
# install the skill into the OpenClaw workspace (symlinks are rejected)
install-skill:
	mkdir -p ~/.openclaw/workspace/skills/auskunft && sed "s#__AUSKUNFT_HOME__#$(CURDIR)#g" skill/SKILL.md > ~/.openclaw/workspace/skills/auskunft/SKILL.md

test:
	uv run pytest -q

coverage:
	uv run pytest -q --cov=auskunft --cov-report=term --cov-report=xml
	uv run python scripts/badge.py
