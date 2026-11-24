"""Bounded immutable cache for anonymous public responses only."""
import gzip
import json
from collections import OrderedDict
from threading import Lock

from fastapi import Response
from fastapi.encoders import jsonable_encoder

from rag_tech_retriever.common.middleware.compression import accepts_gzip


class PublicResponseCache:
    """DB mutation token is part of every key; no personal responses accepted."""
    def __init__(self, capacity: int = 64, max_bytes: int = 2097152):
        if not 1<=capacity<=256 or not 65536<=max_bytes<=8388608:
            raise ValueError("public cache capacity/bytes outside safe bounds")
        self.capacity,self.max_bytes=capacity,max_bytes
        self.entries=OrderedDict()
        self.bytes=0
        self.lock=Lock()

    def get(self,epoch,key):
        with self.lock:
            value=self.entries.get((epoch,key))
            if value is not None:self.entries.move_to_end((epoch,key))
            return value

    def put(self,epoch,key,payload):
        plain=json.dumps(jsonable_encoder(payload),ensure_ascii=False,separators=(",",":"),allow_nan=False).encode()
        compressed=gzip.compress(plain,compresslevel=6,mtime=0)
        value=(plain,compressed);size=len(plain)+len(compressed)
        if size>self.max_bytes:return value
        with self.lock:
            old=self.entries.pop((epoch,key),None)
            if old:self.bytes-=sum(map(len,old))
            self.entries[(epoch,key)]=value;self.bytes+=size
            while len(self.entries)>self.capacity or self.bytes>self.max_bytes:
                _,removed=self.entries.popitem(last=False);self.bytes-=sum(map(len,removed))
        return value

    @staticmethod
    def response(value,accept_encoding):
        """Honor gzip opt-out; immutable payload bytes never change between readers."""
        encoded=accepts_gzip(accept_encoding)
        headers={"Vary":"Accept-Encoding","Cache-Control":"no-store"}
        if encoded:headers["Content-Encoding"]="gzip"
        return Response(value[1] if encoded else value[0],media_type="application/json",headers=headers)
