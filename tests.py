'''
These test cases are based on the parts of the ietf TFTP specification our
server implements.
https://www.ietf.org/rfc/rfc1350.txt

run with trial:
    $ trial tests.py
'''
# stdlib imports
from StringIO import StringIO

# 3rd party imports
from twisted.trial import unittest

# our imports
import tftp

class DummyFileSystem(object):
    def __init__(self, files):
        '''
        files: a sequence of (filename, data)
        '''
        self.files = files

    def getFileData(self, filename, blockno):
        for myFile, data in self.files:
            if myFile == filename:
                handle = StringIO(data)
                handle.seek((blockno - 1) * 512)
                return handle.read(512)

class TestTftp(unittest.TestCase):
    # NB TODO need functional tests to test that:
    # * we start sending data from a different port
    # * we let go of the port at the appropriate times
    # * we handle files not found, or unable to read etc correctly

    def testIntBytes(self):
        self.assertEquals('\x00\x01', tftp.intToBytes(1))
        self.assertEquals(1, tftp.bytesToInt('\x00\x01'))
        self.assertEquals(4, tftp.bytesToInt('\x00\x04'))

    def testReadRequest(self):
        goodData = '\x00\x01woo.txt\x00netascii\x00'
        rr = tftp.ReadRequest(goodData)
        self.assertEquals('woo.txt', rr.filename)
        self.assertEquals('netascii', rr.mode)

        badData = '\x00\x03\x00\x00wooowoowooowoowoo'
        self.assertRaises(tftp.BadDataError, tftp.ReadRequest, badData)

    def testAck(self):
        goodData = '\x00\x04\x00\x01'
        badData = '\x00\x01woo.txt\x00netascii\x00'
        ack = tftp.Ack(goodData)
        self.assertEquals(1, ack.blockno)
        self.assertRaises(tftp.BadDataError, tftp.Ack, badData)
        self.assertRaises(tftp.BadDataError, tftp.Ack, '')

    def testDownload(self):
        rr = tftp.ReadRequest('\x00\x01woo.txt\x00netascii\x00')
        fileData = '0123456789' * 52
        download = tftp.Download(rr, '127.0.0.1', 1111, DummyFileSystem([('woo.txt', fileData)]))
        response = download.makeNextDataMessage()
        self.assertEquals('\x00\x03', response[0:2], 'Read response should start with data opcode')
        self.assertEquals('\x00\x01', response[2:4], 'Read response should then have blockno')
        self.assertEquals(fileData[:512], response[4:], 'Read response should then have file contents.')
        response = download.ack('\x00\x04\x00\x01', '127.0.0.1', 1111)
        self.assertEquals('\x00\x03', response[0:2], 'Read response should start with data opcode')
        self.assertEquals('\x00\x02', response[2:4], 'Read response should then have blockno')
        self.assertEquals(fileData[512:], response[4:], 'Read response should then have file contents.')

    def testDownloadAckOutOfSequence(self):
        rr = tftp.ReadRequest('\x00\x01woo.txt\x00netascii\x00')
        fileData = '0123456789' * 52
        download = tftp.Download(rr, '127.0.0.1', 1111, DummyFileSystem([('woo.txt', fileData)]))
        response = download.makeNextDataMessage()
        self.assertEquals('\x00\x03', response[0:2], 'Read response should start with data opcode')
        self.assertEquals('\x00\x01', response[2:4], 'Read response should then have blockno')
        self.assertEquals(fileData[:512], response[4:], 'Read response should then have file contents.')

        self.assertRaises(tftp.BadDataError, download.ack, '\x00\x04\x00\x02',
            '127.0.0.1', 1111)

        # is ok when correct ack comes
        response = download.ack('\x00\x04\x00\x01', '127.0.0.1', 1111)
        self.assertEquals('\x00\x03', response[0:2], 'Read response should start with data opcode')
        self.assertEquals('\x00\x02', response[2:4], 'Read response should then have blockno')
        self.assertEquals(fileData[512:], response[4:], 'Read response should then have file contents.')

    def testDownloadAckFromWrongSource(self):
        rr = tftp.ReadRequest('\x00\x01woo.txt\x00netascii\x00')
        fileData = '0123456789' * 52
        download = tftp.Download(rr, '127.0.0.1', 1111, DummyFileSystem([('woo.txt', fileData)]))
        response = download.makeNextDataMessage()
        self.assertEquals('\x00\x03', response[0:2], 'Read response should start with data opcode')
        self.assertEquals('\x00\x01', response[2:4], 'Read response should then have blockno')
        self.assertEquals(fileData[:512], response[4:], 'Read response should then have file contents.')

        self.assertRaises(tftp.BadDataError, download.ack, '\x00\x04\x00\x01',
            '127.0.0.1', 1112)

        # is ok when correct ack comes
        response = download.ack('\x00\x04\x00\x01', '127.0.0.1', 1111)
        self.assertEquals('\x00\x03', response[0:2], 'Read response should start with data opcode')
        self.assertEquals('\x00\x02', response[2:4], 'Read response should then have blockno')
        self.assertEquals(fileData[512:], response[4:], 'Read response should then have file contents.')

