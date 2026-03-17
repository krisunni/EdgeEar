# Frequency preset definitions (SDR + stream URLs)

PRESETS = [
    # ── Weather ──
    {
        "id": "noaa-seattle",
        "label": "NOAA Seattle",
        "freq": "162.550M",
        "mode": "fm",
        "category": "weather",
        "squelch": 0,
        "parser": "noaa",
        "stream_url": "https://wxradio.org/streams/seattle.mp3",
        "note": "NWS Seattle 24/7 weather radio",
    },
    {
        "id": "noaa-monterey",
        "label": "NOAA Monterey",
        "freq": "162.400M",
        "mode": "fm",
        "category": "weather",
        "squelch": 0,
        "parser": "noaa",
        "stream_url": "https://wxradio.org/streams/monterey.mp3",
        "note": "NWS Monterey — primary dev/test stream",
    },
    {
        "id": "noaa-portland",
        "label": "NOAA Portland",
        "freq": "162.475M",
        "mode": "fm",
        "category": "weather",
        "squelch": 0,
        "parser": "noaa",
        "stream_url": "https://wxradio.org/streams/portland.mp3",
        "note": "NWS Portland weather radio",
    },
    {
        "id": "kuow-fm",
        "label": "KUOW 94.9",
        "freq": "94.900M",
        "mode": "wbfm",
        "category": "broadcast",
        "squelch": 0,
        "stream_url": "https://npr-ice.streamguys1.com/live.mp3",
        "note": "NPR Seattle",
    },
    # ── Aviation ──
    {
        "id": "ksea-atis",
        "label": "SEA-TAC ATIS",
        "freq": "118.000M",
        "mode": "am",
        "category": "aviation",
        "squelch": 30,
        "stream_url": "https://www.liveatc.net/hlisten.php?mount=ksea_app&icao=ksea",
        "note": "SEA-TAC airport info",
    },
    {
        "id": "ksea-tower",
        "label": "SEA-TAC Tower",
        "freq": "119.900M",
        "mode": "am",
        "category": "aviation",
        "squelch": 30,
        "stream_url": "https://www.liveatc.net/hlisten.php?mount=ksea_twr&icao=ksea",
        "note": "SEA-TAC tower control",
    },
    {
        "id": "ksea-approach",
        "label": "SEA-TAC Approach",
        "freq": "124.200M",
        "mode": "am",
        "category": "aviation",
        "squelch": 30,
        "note": "SEA-TAC approach control — SDR only",
    },
    {
        "id": "kbfi-tower",
        "label": "Boeing Field Tower",
        "freq": "120.600M",
        "mode": "am",
        "category": "aviation",
        "squelch": 30,
        "note": "Boeing Field / King County — SDR only",
    },
    {
        "id": "kpae-tower",
        "label": "Paine Field Tower",
        "freq": "132.950M",
        "mode": "am",
        "category": "aviation",
        "squelch": 30,
        "note": "Paine Field / Snohomish County — SDR only",
    },
    {
        "id": "adsb-1090",
        "label": "ADS-B 1090 MHz",
        "freq": "1090M",
        "mode": "adsb",
        "category": "aviation",
        "squelch": 0,
        "note": "ADS-B aircraft tracking (dump1090) — map-only mode",
        "device_index": 1,
    },
    # ── Marine ──
    {
        "id": "ais-marine",
        "label": "AIS Marine Traffic",
        "freq": "162.000M",
        "mode": "ais",
        "category": "marine",
        "squelch": 0,
        "note": "AIS vessel tracking (rtl_ais) — map-only mode",
    },
    {
        "id": "marine-ch16",
        "label": "Marine CH 16",
        "freq": "156.800M",
        "mode": "fm",
        "category": "marine",
        "squelch": 20,
        "note": "International distress/calling — SDR only",
    },
    {
        "id": "marine-ch22a",
        "label": "Marine CH 22A",
        "freq": "157.100M",
        "mode": "fm",
        "category": "marine",
        "squelch": 20,
        "note": "US Coast Guard liaison — SDR only",
    },
    # ── WEFAX (HF Weather Charts) ──
    {
        "id": "wefax-nmc",
        "label": "NMC Point Reyes",
        "freq": "8682.0k",
        "mode": "usb",
        "category": "wefax",
        "squelch": 0,
        "note": "WEFAX weather charts — HF direct sampling, auto-scheduled",
    },
    {
        "id": "wefax-noj",
        "label": "NOJ Kodiak",
        "freq": "4298.0k",
        "mode": "usb",
        "category": "wefax",
        "squelch": 0,
        "note": "WEFAX weather charts — HF direct sampling, auto-scheduled",
    },
    # ── Public Safety ──
    {
        "id": "kcso-dispatch",
        "label": "King Co Sheriff",
        "freq": "460.125M",
        "mode": "fm",
        "category": "public_safety",
        "squelch": 25,
        "note": "King County Sheriff dispatch — SDR only (may be encrypted)",
    },
    {
        "id": "seattle-fire",
        "label": "Seattle Fire",
        "freq": "460.575M",
        "mode": "fm",
        "category": "public_safety",
        "squelch": 25,
        "note": "Seattle Fire dispatch — SDR only (may be encrypted)",
    },
    # ── Science ──
    {
        "id": "meteor-scatter",
        "label": "Meteor Scatter",
        "freq": "143.050M",
        "mode": "fm",
        "category": "science",
        "squelch": 0,
        "note": "Passive meteor detection — forward scatter on 143.050 MHz carrier",
    },
    # ── Broadcast ──
    {
        "id": "kexp-fm",
        "label": "KEXP 90.3",
        "freq": "90.300M",
        "mode": "wbfm",
        "category": "broadcast",
        "squelch": 0,
        "note": "KEXP Seattle",
    },
]

CATEGORIES = ["weather", "wefax", "aviation", "marine", "science", "public_safety", "broadcast"]

CATEGORY_LABELS = {
    "weather": "Weather",
    "wefax": "WEFAX",
    "aviation": "Aviation",
    "marine": "Marine",
    "science": "Science",
    "public_safety": "Public Safety",
    "broadcast": "Broadcast",
}


def get_presets():
    return PRESETS


def get_presets_by_category():
    grouped = {cat: [] for cat in CATEGORIES}
    for preset in PRESETS:
        grouped[preset["category"]].append(preset)
    return grouped


def get_preset_by_id(preset_id):
    for preset in PRESETS:
        if preset["id"] == preset_id:
            return preset
    return None
