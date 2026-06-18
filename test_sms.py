import os

from twilio.rest import Client

account_sid = os.getenv('TWILIO_ACCOUNT_SID')
auth_token = os.getenv('TWILIO_AUTH_TOKEN')
from_number = os.getenv('TWILIO_PHONE_NUMBER')
to_number = os.getenv('TWILIO_TO_NUMBER')

missing = [name for name, value in {
    'TWILIO_ACCOUNT_SID': account_sid,
    'TWILIO_AUTH_TOKEN': auth_token,
    'TWILIO_PHONE_NUMBER': from_number,
    'TWILIO_TO_NUMBER': to_number,
}.items() if not value]
if missing:
    raise SystemExit(
        'Missing environment variables: ' + ', '.join(missing)
        + '. Set them before running this script.'
    )

client = Client(account_sid, auth_token)
message = client.messages.create(
    body='SENTRI test SMS from the dispatch setup script.',
    from_=from_number,
    to=to_number,
)
print(message.sid)
