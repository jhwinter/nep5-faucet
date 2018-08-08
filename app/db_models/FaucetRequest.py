from pynamodb.models import Model
from pynamodb.attributes import UnicodeAttribute, UTCDateTimeAttribute, NumberAttribute


class FaucetRequest(Model):
    """ Model that stores each request made using a wallet address """

    class Meta:
        """ metadata for the FaucetRequest table stored in DynamoDB"""
        table_name = 'FaucetRequest'
        region = 'us-east-1'
        write_capacity_units = 5  # TODO: change to use auto-scaling once pynamodb supports it
        read_capacity_units = 5

    wallet_address = UnicodeAttribute(hash_key=True)
    last_visited = UTCDateTimeAttribute(range_key=True)
    ttl = NumberAttribute()  # TODO: add in real ttl once pynamodb supports it
