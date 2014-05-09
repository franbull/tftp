'''
Implementing some of:
https://www.ietf.org/rfc/rfc1350.txt

Not implementing:
    writing (putting) files
    modes other then netascii
    returning appropriate errors to the client
'''
import os
import struct

from twisted.internet.protocol import DatagramProtocol
from twisted.internet import reactor


BLOCK_SIZE = 512


opcodeMap = {
        'RRQ': '\x00\x01',
        'WRQ': '\x00\x02',
        'DATA': '\x00\x03',
        'ACK': '\x00\x04',
        'ERROR': '\x00\x05',
        }


def intToBytes(i):
    '''
    eg 3 -> '\x00\x03'
    '''
    # TODO what happens if our file is so big the blockno exceeds the size of
    # an unsigned short? that would be quite big, 2 bytes is 16 bits is 2^16, so
    # file size would be 2^16 * 512 bytes  = 2^15 kb = 2^5 MB = 32 MB. Hmm, not
    # so big actually . . .
    return struct.pack('>H', i)


def bytesToInt(byt):
    '''
    eg '\x00\x03' -> 3
    '''
    return struct.unpack('>H', byt)[0]


class BadDataError(Exception):
    ''' To be raised whenever the data is not as we would prefer.'''
    pass


class FileSystem(object):
    '''
    FileSystem must provide a getFileData method.
    '''
    def __init__(self, directoryPath='/tmp/test_tftp'):
        self.directoryPath = directoryPath

    def readBlock(self, path, blockno):
        with open(path, 'r') as fin:
            fin.seek((blockno - 1) * BLOCK_SIZE)
            return fin.read(BLOCK_SIZE)

    def getFileData(self, requestedFilename, blockno):
        # os.listdir only returns the names of the files in the dir, so compare
        # against that just to make sure there's no directory traversal
        # possibilities
        for filename in os.listdir(self.directoryPath):
            if requestedFilename == filename:
                return self.readBlock(os.path.join(self.directoryPath,
                    filename), blockno)
        # TODO this is an error we should return to the client (and is it
        # really 'bad data'?)
        raise BadDataError('File not found.')


class Ack(object):
    def __init__(self, data):
        if data[:2] != opcodeMap['ACK']:
            # TODO return error messages to the client?
            raise BadDataError('Message is not an ack.')
        self.blockno = bytesToInt(data[2:])


class Download(object):
    def __init__(self, readRequest, remoteHost, remotePort, fileSystem=None):
        self.filename = readRequest.filename
        self.mode = readRequest.mode
        self.remoteHost = remoteHost
        self.remotePort = remotePort
        self.blockno = 0
        self.fileSystem = fileSystem
        if self.fileSystem is None:
            self.fileSystem = FileSystem()
        self.done = False

    def makeNextDataMessage(self):
        blockno, data = self.nextData()
        return '%s%s%s' % (
                opcodeMap['DATA'],
                intToBytes(blockno),
                data)

    def nextData(self):
        self.blockno += 1
        data = self.fileSystem.getFileData(self.filename, self.blockno)
        if len(data) < BLOCK_SIZE:
            self.done = True
        return self.blockno, data

    def ack(self, message, host, port):
        if host != self.remoteHost or port != self.remotePort:
            # TODO error handling
            raise BadDataError('Message from wrong place!')
        ack = Ack(message)
        if ack.blockno != self.blockno:
            #TODO error handling
            raise BadDataError('This ack is out of sequence. ack for blockno %s, current blockno %s' % (ack.blockno, self.blockno))
        return self.makeNextDataMessage()


class TftpDownloadHandler(DatagramProtocol):
    '''
    Subclass of twisted.internet.protocol.DatagramProtocol
    (http://twistedmatrix.com/documents/current/api/twisted.internet.protocol.DatagramProtocol.html)
    Created when the server gets a read request for a file.
    Expects only acks from the remoteHost and remotePort it knows.

    As soon as TftpDownloadHandler is created it sends it's first data packet.

        A transfer is established by sending a request ([...]
        RRQ to read from it), and receiving a
        positive reply, [...] the first data packet for read.


    Data packets look like:
                   2 bytes     2 bytes      n bytes
                   ----------------------------------
                  | Opcode |   Block #  |   Data     |
                   ----------------------------------

                        Figure 5-2: DATA packet
    Where opcode is \x00\x03 DATA

    We send the next block when we get an ack for the last block.
    Ack packets look like:
                         2 bytes     2 bytes
                         ---------------------
                        | Opcode |   Block #  |
                         ---------------------

                         Figure 5-3: ACK packet
    Where opcode is \x00\x04 ACK

    We stop when:

    'the host sending the final
   ACK will wait for a while before terminating in order to retransmit
   the final ACK if it has been lost.  The acknowledger will know that
   the ACK has been lost if it receives the final DATA packet again.
   The host sending the last DATA must retransmit it until the packet is
   acknowledged or the sending host times out.'

    in other words: once we've received an ack for our last message, we can hang
    up
    '''
    # timeout period should actually be longer than this I think
    timeoutPeriod = 5

    def __init__(self, readRequest, remoteHost, remotePort, fileSystem=None):
        self.readRequest = readRequest
        self.remoteHost = remoteHost
        self.remotePort = remotePort
        self.fileSystem = fileSystem
        self.timeout = reactor.callLater(self.timeoutPeriod, self.timedOut)

    def timedOut(self):
        if self.transport is not None:
            self.transport.stopListening()

    def startProtocol(self):
        # make download
        self.download = Download(self.readRequest, self.remoteHost, self.remotePort, self.fileSystem)
        # send first block
        self.transport.write(self.download.makeNextDataMessage(), (self.remoteHost, self.remotePort))

    def datagramReceived(self, data, (host, port)):
        self.timeout.reset(self.timeoutPeriod)
        if self.download.done:
            self.transport.stopListening()
        self.transport.write(self.download.ack(data, host, port), (host, port))


class ReadRequest(object):
    '''
    Parses a message from a client into a read request, or raises an error.
    '''
    def __init__(self, data):
        if len(data) < 2 or data[:2] != opcodeMap['RRQ']:
            # TODO should this be an error message of code 0?
            raise BadDataError('Got a message that is not a read request: %s' % data)
        filename, mode, nothing = data[2:].split('\x00')
        self.filename = filename
        self.mode = mode


class TftpReadRequestHandler(DatagramProtocol):
    '''
    Subclass of twisted.internet.protocol.DatagramProtocol
    (http://twistedmatrix.com/documents/current/api/twisted.internet.protocol.DatagramProtocol.html)
    Listens on port 69 and expects only read requests.

        Read request looks like:

            2 bytes     string    1 byte     string   1 byte
            ------------------------------------------------
           | Opcode |  Filename  |   0  |    Mode    |   0  |
            ------------------------------------------------
                    Figure 5-1: RRQ/WRQ packet

    Where Opcode is \x00\x01
    '''
    def datagramReceived(self, data, (host, port)):
        '''
        When we get a read request, start a new port sending data and listening
        for acks by calling listenUDP with TftpDownloadHandler.
        '''
        readRequest = ReadRequest(data)
        # Spec says pick a random port.
        reactor.listenUDP(0, TftpDownloadHandler(readRequest, host, port))


if __name__ == '__main__':
    reactor.listenUDP(69, TftpReadRequestHandler())
    print 'serving files'
    reactor.run()
