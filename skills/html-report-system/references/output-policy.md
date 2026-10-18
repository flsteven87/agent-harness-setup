# Project Report Output Policy

Resolve the destination before writing a delivered HTML report.

1. Use an explicit user destination when one is supplied.
2. For a repository-bound report, read the target repository's `AGENTS.md` and the documentation
   policy it names. Use the exact report owner, path, naming rule, source-versus-mirror contract, and
   lifecycle that policy assigns.
3. For a report spanning repositories, use the repository whose policy owns the report. Ask the user
   when ownership remains ambiguous.
4. An existing `docs/` or report directory is not authority. When repository policy assigns no path
   or lifecycle to this report family, stop before writing and ask for a project destination or policy
   decision.
5. For work with no repository context, require an explicit destination.

Temporary working data and browser previews may use the OS temporary directory. A delivered report
may not fall back to a temporary directory, Desktop, or another home-folder location.

On delivery, return the repository-relative and absolute paths. Identify the authoritative source
and any generated HTML mirror when the repository distinguishes them.
