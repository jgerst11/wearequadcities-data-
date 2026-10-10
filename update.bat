@echo off
cd /d "C:\Users\jgers\wearequadcities-data"

rem Start every run from GitHub's latest copy. GitHub Actions also commits events.json/news.json,
rem and a plain pull --rebase used to leave this repo stuck mid-rebase. Only generated JSON is discarded.
git rebase --abort >nul 2>&1
git fetch origin
git reset --hard origin/master

echo Fetching news...
python news_fetch.py

echo Fetching events (visitqc + Eventbrite)...
python events_fetch.py

git add events.json news.json
git diff --cached --quiet && echo No changes. || (
    git commit -m "chore: update events + news [skip ci]"
    git push || (
        rem GitHub updated in the meantime: replay our commit on top, keeping our fresh JSON.
        git pull --rebase -X theirs && git push
    )
)
echo Done.
pause
