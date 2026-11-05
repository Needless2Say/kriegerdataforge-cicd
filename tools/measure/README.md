# The measure

`kdf_measure.py` prints where each secret and rule of an account sits, by name and setting alone, and never a value.
Run before a change to the account's settings and again after it, the two outputs compare line by line.

## What it reads

For every repository the signed in login owns, or each one `--repo` names.

- The visibility, the default branch, whether it is archived or a fork.
- Whether Actions runs, which actions it allows, and the default permissions of a workflow's own token.
- The repository's secrets and variables, by name.
- Each environment, its branch rule (any branch, protected branches, or selected branches and tags), its branch and
  tag policies, its required reviewers and wait timer, whether admins may bypass it, and its secrets and variables by
  name.
- The classic protection of `main` and of the default branch, every setting by name.
- The rules that reach `main`, and every ruleset with its target, its refs, its rules and who may bypass it.
- The collaborators with their roles, the pending invitations, and the deploy keys by title with whether each is read
  only.

Then every GitHub App installation the login can see, with the App's id, its permissions, events and repositories, so
an App id named elsewhere can be matched to the App it belongs to, the login's plan
and the scopes of the token `gh` holds, and whether the plan offers rulesets and the admin bypass switch on a private
repository, as the private repositories answered.

## What it never reads or prints

- A secret's value, which GitHub never returns.
- A variable's value or a deploy key's public key, which GitHub returns and the script never puts in a line.
- Webhooks, since a hook's URL can carry a credential.
- The login's token, since every call goes through `gh api` and the token stays inside `gh`.

Before anything is printed, the whole output is checked for the shape of a credential, a GitHub token, a private key,
a JSON web token, a URL with a password, or a run of 24 or more letters and digits mixing upper and lower case. One
match refuses the whole output, exit 2, naming the line by its number and the shape alone.

## Running it

It needs Python 3.11 or newer and the GitHub CLI signed in. It uses the standard library alone, so any such
interpreter runs it, with no install.

```bash
python tools/measure/kdf_measure.py > measure.txt
python tools/measure/kdf_measure.py --repo some-repo --repo another-repo > measure.txt
python tools/measure/kdf_measure.py --login-only
```

Run it from a checkout of `main`, so the script that reads is the script that was reviewed.

| Exit | Meaning |
| --- | --- |
| 0 | Every read answered |
| 1 | A read was refused or failed, each named by an `unreadable` line, the rest still printed |
| 2 | The output held a credential's shape and nothing was printed |
| 3 | `gh` could not run, or the login could not be read |

A read the plan does not offer on a private repository, such as rulesets on a plan without them, is printed as
`unavailable` and counts as an answer, not a failure.

## The lines

Each line names what it describes first, so a line by line comparison of two runs shows each change on its own line.

```text
repo <name> visibility=private default_branch=main archived=false fork=false
repo <name> secret <NAME>
repo <name> environment <env> admin_bypass=false branch_rule=selected reviewers=User:<login> ...
repo <name> environment <env> policy branch main
repo <name> ruleset <id> name=<name> target=tag enforcement=active include=refs/tags/v* rules=deletion,update ...
installation <app> app_id=<id> id=<id> account=<login> selection=selected permissions=contents:read,secrets:write ...
unreadable repo <name> collaborators status=403
```

A value with a space or an equals sign is quoted as JSON, and an empty list prints as `-`.

Its tests are `scripts/tests/test_kdf_measure.py`, run by `make ci` against a fake GitHub API.
