# Interface design

Reviewed and revised on 16 November 2026.

Pink Party is a small call interface for a game night. Joining, seeing the room state and finding the microphone controls take priority. Pink remains the main colour; the farmhouse carries the game theme.

## Research used

The research compared Anthropic’s Frontend Design, Impeccable and community discussions of anti-slop skills. The [skills directory](https://skills.sh/) listed Frontend Design among its widely installed skills. That indicates adoption; the decision to use its guidance came from reading the source and matching it to this app.

- [Anthropic Frontend Design](https://github.com/anthropics/skills/blob/main/skills/frontend-design/SKILL.md): subject-specific choices, restrained decoration, action labels and screenshot review. Applied by removing the promotional hero, repeated slogans, tracked uppercase labels and decorative arrows.
- [Impeccable](https://github.com/pbakaus/impeccable): its [Operate guidance](https://github.com/pbakaus/impeccable/blob/main/skill/reference/operate.md) prioritises familiar controls, clear state and responsive structure. Used as a published reference, without installing its CLI, hooks or account integration.
- [Humanizer](https://github.com/blader/humanizer), read from the career workspace’s pinned skill: applied to the README, interface text and sample session copy. Technical claims and evidence limits remain explicit.

These sources informed the revision. No third-party skill installer or generated design system was added to the app.

## Visual choices

| Element    | Choice                                                                                      |
| ---------- | ------------------------------------------------------------------------------------------- |
| Background | Rose `#f8edf2`, flat rather than a decorative gradient.                                     |
| Surface    | Pale pink-white `#fffafd` for the voice room.                                               |
| Text       | Plum `#432c39`, secondary mauve `#775c6b`.                                                  |
| Action     | Berry `#a42d5c`; green and amber identify connection states.                                |
| Type       | Self-hosted Nunito Sans, with larger weights for headings and a 16px input size.            |
| Layout     | Voice room first; fictional game-night plan alongside it on desktop and below it on mobile. |

The farmhouse uses a two-pixel grid with stepped roof edges, tile seams, timber windows, porch steps and planting beds. It is decorative original artwork, not an official game asset. SVG is retained so the illustration stays sharp without an external image request.

The page uses one heading, standard form labels, inline recovery messages and a participant list. Form controls have visible keyboard focus and at least 48px height. Private mode hides the join-code field and allows the name field to fill the row. Reduced-motion preferences disable transitions. The sample plan remains labelled as fictional and does not imply calendar or game-launch functionality.

## Verification

The revision passed `npm run check` (TypeScript, 14 offline tests, production build and Prettier), all 13 local browser cases, and both synthetic TLS/identity-proxy cases. The private suite also checks that the display-name input fills the available row when the join-code field is hidden. Real Tailscale Serve was not rerun for this interface revision.

The responsive check covers 320, 390, 680, 900 and 1440px widths, page overflow, the keyboard skip link and the join button’s touch target. Desktop, mobile and four-participant screenshots were refreshed from the running app. The four participants and their audio are synthetic test clients.

Axe-core 4.11.0 reported no violations or incomplete checks on the empty room at all five widths using WCAG 2 A/AA, WCAG 2.1 AA and best-practice rules. The connected and muted room also passed at 320px with a 32-character display name and no page overflow. The mute control changes its label colour and background together, including on hover, so toggling does not briefly show white text on a pale background. These automated checks supplement visual and keyboard inspection; they do not establish full accessibility conformance.

The first cold offline run hit the existing startup fixture’s three-second lookup deadline. The isolated test and complete subsequent check passed without a startup implementation change. Vite’s existing warning about a JavaScript chunk larger than 500 kB remains.

Historical voice and network evidence remains in the dated validation reports; this revision does not establish new remote-call results.
