# <repo> cloud startup

A Python library. No services start and nothing needs to be running. The checkout is `/workspace/<repo>`, and the
install script made its `.venv` with Python 3.14.

Initialize each shell:

```bash
cd /workspace/<repo>
export PIP_DISABLE_PIP_VERSION_CHECK=1
export GIT_TERMINAL_PROMPT=0
source .venv/bin/activate
python --version
```

Python must be 3.14. If `.venv` is missing or broken, run the install script again.

What this environment leaves out on purpose. The owner's private development packages, kdf-fmt among them, are not
installed, so `make setup` and `make ci-style` do not run here. The agent reaches `github.com` alone, so `pip-audit`
and installs from PyPI do not run either. Never ask for a token or a credential. Run tests with the repo's own make
targets, for example `make test`.
