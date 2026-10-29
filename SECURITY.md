# Security policy

wanna.sh runs AI models and, with Code, programs an AI writes, on people's own computers. Security reports are very
welcome.

## Reporting a vulnerability

Please report it **privately**: open the repository's **Security** tab and choose **Report a vulnerability**
(<https://github.com/wanna-sh/wanna/security/advisories/new>). Don't open a public issue, discussion or pull request
for a security problem.

It helps to include:

- what the problem is and what an attacker could do with it;
- steps to reproduce it, or a proof of concept;
- the commit or version, your operating system, and how wanna.sh was installed (installer, by hand, or Docker, with or
  without Code turned on).

You'll get a reply as soon as possible. Please give us reasonable time to release a fix before sharing details
publicly; we're happy to credit you in the advisory.

## Supported versions

| Version | Supported |
| --- | --- |
| The latest release, and `main` | Yes |
| Older releases | No: please update |

Security fixes go to `main` and into the next release. To update, run the installer again, or `docker compose pull` for
Docker. Releases are listed at <https://github.com/wanna-sh/wanna/releases>.

## Scope

How wanna.sh is meant to protect people is described on the website:
<https://wanna.sh/docs/reference/security/>. Anything that breaks those promises is in scope, including:

- the server and its APIs (`/v1`, `/api`), API keys, and the browser protections (Origin, Host and CORS checks);
- the Code sandbox: escaping it, reaching the computer, the local network or wanna.sh from inside it, or getting past
  its approval modes;
- the `web_fetch` tool reaching local or private addresses;
- the installer, the Docker image and the compose files, including the optional Docker socket setup;
- Knowledge: documents, libraries and search;
- model loading running code from a model repository.

Usually out of scope (but tell us if wanna.sh makes them worse):

- bugs in the projects wanna.sh builds on (llama.cpp, PyTorch, diffusers, transformers, SearXNG, Docker): please report
  those to them;
- what AI models say or make, and their licences;
- setups that switch protections off on purpose, such as `WANNA_CORS=*`, `WANNA_ALLOWED_HOSTS=*`, or publishing wanna.sh
  on a network without **Require API key**;
- attacks that need control of the computer already (for example an administrator account).
