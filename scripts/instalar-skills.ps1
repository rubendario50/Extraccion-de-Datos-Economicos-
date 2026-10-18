# Instala las skills de diseño que usa el proyecto en Claude Code (nivel usuario).
# Requiere Node.js. Uso: powershell -ExecutionPolicy Bypass -File scripts\instalar-skills.ps1

npx -y skills add pbakaus/impeccable -g -a claude-code --copy -y
npx -y skills add Leonxlnx/taste-skill -s design-taste-frontend -g -a claude-code --copy -y
