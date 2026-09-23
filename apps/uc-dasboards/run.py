"""Production entry point for Databricks Apps.

Databricks supplies the listening port at runtime.  Resolve it in Python
because app.yaml commands are not evaluated by a shell.
"""

import os


def main() -> None:
    port = int(os.environ.get("DATABRICKS_APP_PORT", "8000"))
    os.execvp(
        "gunicorn",
        [
            "gunicorn",
            "app:server",
            "--bind",
            f"0.0.0.0:{port}",
            "--workers",
            "1",
            "--threads",
            "8",
            "--timeout",
            "180",
            "--access-logfile",
            "-",
            "--error-logfile",
            "-",
        ],
    )


if __name__ == "__main__":
    main()
