# Contributing

Thanks for helping to make Shrinkarr better. Shrinkarr is developed in this repository only.

## Ideas and bugs

Open an issue. For a bug, add what you did, what you expected, what happened, and the relevant part of `journalctl -u shrinkarr` (remove API keys and addresses you don't want to share). For a conversion that failed, the ffmpeg log is in the History page.

## Pull requests

Pull requests are welcome. Shrinkarr is licensed under the [PolyForm Strict License 1.0.0](LICENSE), which does not allow changes in general. As an additional permission, you may make changes to the software **for the sole purpose of submitting them as a pull request to this repository**. By opening a pull request you agree that your contribution may be used, changed and distributed by the licensor as part of Shrinkarr, under the license of the project.

A few guidelines:

- Keep the code in the style of the surrounding code; the web UI has no build step and no dependencies.
- Every text in the UI goes through `t()` and exists in both languages in `app/static/i18n.js`. Texts the server stores or sends are in `app/i18n.py`.
- Test a change on a real conversion before you open the pull request, and describe how you tested it.
- Don't change what happens to a user's files (verification, replacing) without explaining why it is still safe.
