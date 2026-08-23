# Setup

Five steps. The whole thing runs on GitHub's free tier.

## 1. Create the profile repository

Make a **public** repository named exactly your username. If your username is
`ansxyz`, the repository must be `ansxyz/ansxyz`. GitHub treats that one repo
specially and renders its README on your profile page. Any other name and the
card will not show up.

## 2. Copy these files in

```
README.md
SETUP.md
telemetry.py
requirements.txt
.gitignore
cache/.gitkeep
svg/templates/dark.svg      <- edit this
svg/templates/light.svg     <- edit this
svg/dark_mode.svg           <- generated, do not hand-edit
svg/light_mode.svg          <- generated, do not hand-edit
.github/workflows/telemetry.yml
```

The two files in `svg/templates/` hold the `{{TOKEN}}` placeholders and are
the ones you edit. The two in `svg/` are the rendered output the README points
at; the workflow overwrites them on every run.

## 3. Create a personal access token

Settings → Developer settings → Personal access tokens → Tokens (classic) →
Generate new token. Tick **`repo`** and **`read:user`**. Copy the value.

Then in the profile repository: Settings → Secrets and variables → Actions →
New repository secret, named exactly `ACCESS_TOKEN`, with that value pasted in.

Do not substitute the built-in `GITHUB_TOKEN`. It cannot read contributor
statistics for private repositories or your full commit history, so the commit
and line counts come out far too low.

## 4. Let Actions write to the repo

Settings → Actions → General → Workflow permissions → **Read and write
permissions**. Without this the render succeeds but the commit at the end of
the job is rejected.

## 5. Run it

Actions tab → **downlink** → Run workflow. It takes a couple of minutes; most
of that is GitHub computing contributor statistics for repositories it has not
been asked about recently. The first run is the slow one, since the cache in
`cache/loc.json` is empty. Later runs only recount repositories that have been
pushed to since.

After that it runs itself every six hours, and on any push that touches the
templates or the script.

## Editing

Three lines near the top of `telemetry.py` are yours to write. They are not
pulled from the API:

```python
ROLE = "MS ECE @ KAUST -- Communication Theory Lab"
FOCUS = "wireless comms · LEO satellite PHM · IoT"
LOCATION = "Thuwal, SA"
```

The README has placeholder contact links (`you@example.com` and bare
`scholar.google.com` / `linkedin.com` URLs). Replace them before you publish,
or delete the line.

Colours live in the `<style>` block at the top of each template. Dark and light
are separate files, so a change to one needs the same change in the other.

## If something breaks

**The card shows but every number is 0.** `ACCESS_TOKEN` is missing or lacks
scopes. Check the workflow log for a 401.

**Line counts look far too low.** The `stats/contributors` endpoint returns 202
while GitHub computes results in the background. The script retries, but on a
first run against many repositories some may still be unresolved. Run the
workflow again; the ones that resolved are now cached and the rest get another
attempt.

**Job fails at the push step.** Workflow permissions are still read-only. See
step 4.

**Card looks stale on your profile.** GitHub proxies images through its own
cache. Force a refresh with a hard reload, or wait it out.

## Attribution

The idea of a self-updating SVG statistics card driven by GitHub Actions comes
from [Andrew6rant/Andrew6rant](https://github.com/Andrew6rant/Andrew6rant).
The artwork, layout, and code here are separate work; if you want his
neofetch-style terminal card specifically, fork his repository instead.
