@echo off
cd /d "C:\Users\jgers\wearequadcities-data"

git pull --rebase

echo Fetching news...
python news_fetch.py

echo Fetching events (visitqc + Eventbrite)...
python events_fetch.py

git add events.json news.json
git diff --cached --quiet && echo No changes. || (
    git commit -m "chore: update events + news [skip ci]"
    git push
)
echo Done.
pause
