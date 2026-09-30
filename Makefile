
# install the skill into the OpenClaw workspace (symlinks are rejected)
install-skill:
	mkdir -p ~/.openclaw/workspace/skills/auskunft && sed "s#__AUSKUNFT_HOME__#$(CURDIR)#g" skill/SKILL.md > ~/.openclaw/workspace/skills/auskunft/SKILL.md
