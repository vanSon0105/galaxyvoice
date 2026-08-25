# Retire embedded VoiceStudio after verified cutover

Type: task
Status: open
Blocked by: 15

## Question

After the parity gate passes, how should Galaxy remove VoiceStudio navigation,
runtime management, installer paths, and user data dependencies while keeping
existing projects and the immutable snapshot recoverable from repository
history?

## Done when

The user explicitly approves removal after a successful migration rehearsal,
and Galaxy starts without launching or requiring VoiceStudio.
