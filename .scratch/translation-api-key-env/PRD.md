# Galaxy translation API keys in User Environment

Store a pasted translation API key in the current Windows user's environment
under a provider-specific `GALAXY_*_API_KEY` name. The secret must never be
written to app config, logs, API responses, or Git-tracked files.

The dubbing UI saves pasted values immediately, saves manually typed values on
blur, and then shows only a masked configured state.

