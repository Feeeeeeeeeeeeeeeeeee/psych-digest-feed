#!/bin/zsh
cd ~/Desktop/psych_digest

# 1. Fetch latest state from GitHub Actions
echo "Fetching latest cloud changes..."
git fetch origin main

# 2. Rebase, automatically taking remote versions for any generated data collisions
git rebase -X theirs origin/main

# 3. Add and push if there are local modifications
if [ -n "$(git status --porcelain)" ]; then
    echo "Syncing local changes up to GitHub..."
    git add .
    git commit -m "Local update & sync: $(date +'%Y-%m-%d %H:%M')"
    git push origin main
    echo "Sync complete!"
else
    echo "Everything already up to date."
fi
