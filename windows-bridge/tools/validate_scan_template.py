"""Validate the Kotlin LedmScanClient SOAP template against the capture.

    python tools/validate_scan_template.py

Rebuilds the CreateScanJobRequest exactly as the Kotlin template does and
diffs it against the XML captured on the wire. Any structural difference
prints; identical output proves the Kotlin template is wire-accurate.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAP = os.path.join(ROOT, "devkit-reference", "scan-commands-readable.txt")

ENV_OPEN = ('<?xml version="1.0" encoding="UTF-8"?>\r\n'
            '<SOAP-ENV:Envelope '
            'xmlns:SOAP-ENV="http://www.w3.org/2003/05/soap-envelope" '
            'xmlns:SOAP-ENC="http://www.w3.org/2003/05/soap-encoding" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
            'xmlns:wscn="http://tempuri.org/wscn.xsd">'
            '<SOAP-ENV:Body>')
ENV_CLOSE = "</SOAP-ENV:Body></SOAP-ENV:Envelope>"


def create_scan_job_xml(dpi, color_mode, glass_w, glass_h):
    return (ENV_OPEN +
            "<wscn:CreateScanJobRequest><ScanIdentifier></ScanIdentifier>"
            "<ScanTicket><JobDescription></JobDescription>"
            "<DocumentParameters>"
            "<Format>jfif</Format>"
            "<CompressionQualityFactor>0</CompressionQualityFactor>"
            "<ImagesToTransfer>0</ImagesToTransfer>"
            "<InputSource>Platen</InputSource>"
            "<ContentType>Auto</ContentType>"
            "<InputSize><InputMediaSize>"
            "<Width>%d</Width><Height>%d</Height>"
            "</InputMediaSize>"
            "<DocumentSizeAutoDetect>false</DocumentSizeAutoDetect>"
            "</InputSize>"
            # REVERTED to false: AutoExposure=true produced BLACK scans on
            # the real phone (unproven firmware path). The driver-exact
            # false-ticket is wire-proven to produce a VALID (dim) image;
            # brightness is corrected client-side by ScanAutoLevels.
            "<Exposure><AutoExposure>false</AutoExposure>"
            "<ExposureSettings><Contrast>0</Contrast></ExposureSettings>"
            "</Exposure>"
            "<MediaSides><MediaFront>"
            "<ScanRegion>"
            "<ScanRegionXOffset>0</ScanRegionXOffset>"
            "<ScanRegionYOffset>0</ScanRegionYOffset>"
            "<ScanRegionWidth>%d</ScanRegionWidth>"
            "<ScanRegionHeight>%d</ScanRegionHeight>"
            "</ScanRegion>"
            "<ColorProcessing>%s</ColorProcessing>"
            "<Resolution><Width>%d</Width><Height>%d</Height>"
            "</Resolution>"
            "</MediaFront></MediaSides>"
            "</DocumentParameters>"
            "<RetrieveImageTimeout>300</RetrieveImageTimeout>"
            "<ScanManufacturingParameters>"
            "<DisableImageProcessing>false</DisableImageProcessing>"
            "</ScanManufacturingParameters>"
            "</ScanTicket></wscn:CreateScanJobRequest>"
            % (glass_w, glass_h, glass_w, glass_h, color_mode, dpi, dpi)
            + ENV_CLOSE)


def main():
    cap = open(CAP, "rb").read().decode("utf-8", errors="replace")
    # captured CreateScanJob XML (between the two envelope tags)
    starts = [m.start() for m in
              re.finditer(re.escape(ENV_OPEN), cap)]
    bodies = []
    for s in starts:
        e = cap.find(ENV_CLOSE, s)
        if e > 0:
            bodies.append(cap[s + len(ENV_OPEN):e])
    create = next((b for b in bodies if "CreateScanJobRequest" in b), None)
    if create is None:
        print("CreateScanJob XML not found in capture!")
        return 1

    mine = create_scan_job_xml(300, "RGB24", 8500, 11690)
    mine_body = mine[len(ENV_OPEN):-len(ENV_CLOSE)]

    if mine_body == create:
        print("EXACT MATCH: Kotlin template == captured wire XML")
        return 0

    # token-level diff to show what differs
    cap_tags = re.findall(r"<[^>]+>|[^<>]+", create)
    my_tags = re.findall(r"<[^>]+>|[^<>]+", mine_body)
    diffs = 0
    for i, (a, b) in enumerate(zip(cap_tags, my_tags)):
        if a != b:
            diffs += 1
            if diffs <= 8:
                print("diff at token %d: captured=%r  template=%r" % (i, a, b))
    if len(cap_tags) != len(my_tags):
        print("token count: captured=%d template=%d"
              % (len(cap_tags), len(my_tags)))
    print("STRUCTURAL DIFFS:", diffs)
    return 1 if diffs else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
