from io import BytesIO

import qrcode
from django.core.files.base import ContentFile


def generate_event_qr_code(event, public_url):
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=12,
        border=2,
    )
    qr.add_data(public_url)
    qr.make(fit=True)

    image = qr.make_image(fill_color="#241f22", back_color="#fffaf7").convert("RGB")
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    filename = f"{event.slug}-qr.png"
    if event.qr_code_image:
        event.qr_code_image.delete(save=False)
    event.qr_code_image.save(filename, ContentFile(buffer.getvalue()), save=False)
    event.save(update_fields=["qr_code_image", "updated_at"])
    return event.qr_code_image
