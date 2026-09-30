Lokaler Test ohne Home Assistant:

    python3 tests/mock_github.py 18081 &
    echo '{"github_repo":"test/repo"}' > /tmp/options.json
    OPTIONS_FILE=/tmp/options.json CACHE_DIR=/tmp/cache GH_API_BASE=http://127.0.0.1:18081 PORT=18099 \
      python3 morgenbriefing/server.py
    curl http://127.0.0.1:18099/
