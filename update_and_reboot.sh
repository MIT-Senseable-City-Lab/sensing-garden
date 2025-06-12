cd /home/sg/sensing-garden
git fetch origin
if ! git diff --quiet HEAD origin/prod; then
    git pull origin prod
    sudo shutdown -r now
fi