"""Start the app: python -m app"""

import webbrowser

import uvicorn

from . import config


def main() -> None:
    url = f"http://{config.HOST}:{config.PORT}"
    print(f"Job Search running at {url}  (Ctrl+C to stop)")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    uvicorn.run("app.server:app", host=config.HOST, port=config.PORT, log_level="warning")


if __name__ == "__main__":
    main()
