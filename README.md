# Hunter Douglas Platinum for Home Assistant

A local integration for the **Hunter Douglas Platinum gateway** (the one the *Platinum App* talks to) with full control:

| What | How it shows up in Home Assistant |
|---|---|
| Bottom rail | Main cover of each shade (`cover.<shade>`) |
| Top-down/bottom-up middle rail | Second cover `cover.<shade>_middle_rail` |
| Vanes (Silhouette, Pirouette, etc.) | Tilt control on the main cover, once the vane code is set |
| Scenes stored in the gateway | `scene.<name>` |
| Any other feature the gateway reports | `cover.<shade>_feature_NN` (handy for discovery) |

It talks to the gateway directly over your LAN (TCP port 522), so there's no cloud and no app to decompile — the Platinum App uses the same plain-text protocol.

## Install

### With HACS (recommended)

1. HACS → ⋮ menu → **Custom repositories** → add `https://github.com/walschots/hacs-hunterdouglas-platinum`, type **Integration**.
2. Search HACS for **Hunter Douglas Platinum**, download it, and restart Home Assistant.

HACS shows an update notice whenever a new release is published here.

### Manually

1. Give the gateway a fixed IP address in your router (the Platinum App shows its current IP).
2. Copy `custom_components/hunterdouglas_platinum` into your Home Assistant `config/custom_components/` folder (or add this repo to HACS as a custom repository).
3. Restart Home Assistant.
4. **Settings → Devices & services → Add integration → Hunter Douglas Platinum**, enter the IP.

Close the Platinum App on your phone while adding it: the gateway only handles one connection at a time.

## Getting the middle rail and vanes on your dashboard

* **Vanes**: code `07` is the default. Every blind that reports it gets a **Vanes** slider (`cover.<blind>_vanes`), plus a tilt control on the main cover.
* **Middle rail**: if a top-down/bottom-up blind has no *Middle rail* entity, open the integration → **Configure** → tick it under *Top-down/bottom-up shades*. The same screen has *Shades with vanes* for vane blinds that weren't detected.
* **Combined card**: the integration ships its own dashboard card and loads it automatically. Edit a dashboard → *Add card* → search **Hunter Douglas Platinum blind** → pick any of the blind's entities. It mirrors the Platinum App: a vertical slider per control (Bottom Rail, Middle Rail, Vanes — only the ones the blind has) that moves the way the rail moves, Open/Close quick buttons at each end, and Open/Close for the whole blind in the header. List several blinds under `entities:` to operate a whole room at once. See `dashboard_card_example.yaml`.
* Blinds also appear on Home Assistant's built-in *Climate* dashboard. That's by design (HA counts covers as climate-relevant), not something this integration sets.

## Finding the vane code (one time)

The gateway reports a position for every feature a shade supports. Bottom rail is `04` and middle rail is `18`; the vane code isn't publicly documented, so the integration discovers it:

1. After setup, shades with vanes get an extra entity like **"Feature 07"**. Move it and watch which part of the blind moves.
2. Or run the probe from any computer on your network and tilt vanes in the Platinum App:
   ```
   python3 tools/platinum_probe.py 192.168.1.50 watch
   ```
   The `CHANGE ... feature NN` line tells you the code.
3. Go to the integration → **Configure** → *Vane feature code* → enter `NN`. The vanes then appear as the tilt slider on the shade's main cover, and the raw "Feature NN" entity goes away.

## Options

* **Polling interval** — default 60 s. Platinum shades are one-way radio, so the gateway only knows the last commanded position; the integration updates state immediately after each command.
* **Invert middle rail** — flip it if *open* moves the middle rail the wrong way on your shades.
* **Create entities for unrecognised features** — turn off once you've found your vane code.

## Services

* `hunterdouglas_platinum.set_feature` — send any shade/feature a position (0–100 %) or raw level (0–255). Good for testing.
* `hunterdouglas_platinum.refresh` — re-reads the gateway and returns rooms, shades, feature codes and the raw output (use *Developer tools → Actions*, tick "return response").

## Notes

* Moves issued within 0.4 s of each other are sent in one gateway session, so moving a whole room at once is reliable.
* For room-wide control, put the covers in a Home Assistant cover group.
* Vanes on Platinum blinds typically only tilt when the bottom rail is fully closed; the gateway enforces this, not the integration.

## Protocol reference

```
$dat              -> configuration + positions, ends with $upd01-
  $crRR-TT-..-Name  room RR, shade type TT (02/13 = top-down/bottom-up)
  $csSS-RR-..-Name  shade SS in room RR
  $cpSS-FF-LLL-     shade SS, feature FF, level 000-255
  $cmNN-..-Name     scene NN
$pssSS-FF-LLL     stage a move   -> $done
$rls              execute staged -> $act00-00-
$inmNN-           run scene      -> $act00-00-
$dmy              ping           -> $ack
```

Protocol details come from earlier community work on the Platinum gateway (schwark's SmartThings/Hubitat drivers and schemers' Homebridge plugin).
