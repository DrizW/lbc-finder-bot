from lbc import Client, Sort

from model import Search


class LeboncoinSource:
    name = "leboncoin"

    def __init__(self, request_verify: bool = True):
        self._request_verify = request_verify

    def search(self, search: Search):
        client = Client(proxy=search.proxy, request_verify=self._request_verify)
        response = client.search(**search.parameters._kwargs, sort=Sort.NEWEST)
        return list(response.ads)
