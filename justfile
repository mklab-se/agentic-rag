# Voltrieve shortcuts. Run `just` to list them.

_default:
    @just --list

# Chat with a backend: loop, prompt or hosted
chat backend="loop" *flags="":
    uv run --project clients/cli voltrieve chat --backend {{backend}} --az-token {{flags}}

# Chat and watch every step
trace backend="loop":
    @just chat {{backend}} --trace

# Ask one question
ask question backend="loop":
    uv run --project clients/cli voltrieve ask "{{question}}" --backend {{backend}} --az-token
