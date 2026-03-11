# Release Checklist

This document is intended for app maintainers and outlines the steps to perform when releasing a new version of the app.

!!! important
    Before starting, make sure your **local** `develop`, `main`, and (if applicable) the current LTM branch are all up to date with upstream!

    ```
    git fetch
    git switch develop && git pull # and repeat for main/ltm
    ```

## All Releases from `develop`

### Verify CI Build Status

Ensure that continuous integration testing on the `develop` branch is completing successfully.

### Bump the Version

Update the package version using `poetry version` if necessary ([poetry docs](https://python-poetry.org/docs/cli/#version)). This command shows the current version of the project or bumps the version of the project and writes the new version back to `pyproject.toml` if a valid bump rule is provided.

The new version must be a valid semver string or a valid bump rule: `patch`, `minor`, `major`, `prepatch`, `preminor`, `premajor`, `prerelease`. Always try to use a bump rule when you can.

Display the current version with no arguments:

```no-highlight
> poetry version
nautobot-custom-tunnel-builder 0.2.3a1
```

### Update the Changelog

!!! note
    - This project uses `towncrier` to track human readable changes, so all merged PRs will have one or more entries in the release notes.
    - You will need to have the project's poetry environment built at this stage, as the towncrier command runs **locally only**. If you don't have it, run `poetry install` first.

First, create a release branch off of `develop` (`git switch -c release-X.Y.Z develop`) and automatically generate release notes with `invoke generate-release-notes`.

Stage any remaining files and check the diffs to verify all of the changes are correct (`git diff --cached`).

Commit `git commit -m "Release vX.Y.Z"` and `git push` the staged changes.

### Submit Release Pull Request

Submit a pull request titled `Release vX.Y.Z` to merge your release branch into `main`. Copy the documented release notes into the pull request's body.

!!! important
    Do not squash merge this branch into `main`. Make sure to select `Create a merge commit` when merging in GitHub.

Once CI has completed on the PR, merge it.

### Create a New Release in GitHub

Draft a [new release](https://github.com/nrtc-ops/nautobot-app-custom-tunnel-builder/releases/new) with the following parameters.

* **Tag:** Input current version (e.g. `vX.Y.Z`) and select `Create new tag: vX.Y.Z on publish`
* **Target:** `main`
* **Title:** Version and date (e.g. `vX.Y.Z - 2024-04-02`)

Publish the release!
