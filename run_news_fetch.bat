@echo off
cd /d "C:\Users\jgers\wearequadcities-data"
python news_fetch.py
git add news.json
git diff --cached --quiet && echo No changes. || (
    git commit -m "chore: update news.json [skip ci]"
    git push
)
