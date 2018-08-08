from pynamodb.models import Model
from pynamodb.attributes import UnicodeAttribute, UTCDateTimeAttribute, NumberAttribute


class IPRequest(Model):
    """ Model that stores each request made coming from an IPv4 address """

    class Meta:
        """ metadata for the IPRequest table stored in DynamoDB """
        table_name = 'IPRequest'
        region = 'us-east-1'
        write_capacity_units = 5  # TODO: change to use auto-scaling once pynamodb supports it
        read_capacity_units = 5

    ip_address = UnicodeAttribute(hash_key=True)
    last_visited = UTCDateTimeAttribute(range_key=True)
    ttl = NumberAttribute()  # TODO: add in real ttl once pynamodb supports it
    # a ttl attribute would allow more automated database management and keep our storage usage to a minimum
    # as I would set it to delete entries older than a week old.
    # However, I think I should keep the check logic the same/similar though just in case the automated
    # deletion malfunctions or takes longer than anticipated.
