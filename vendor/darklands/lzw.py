# Source: vvendigo/Darklands (MIT) — unchanged, Python 3 compatible as-is
# Based on JCivED PIC handling code, fixed and optimized

class LZWDictionary:

    def __init__(self, dicIndexMaxBits):
        self.dicTableLen = (0x1 << dicIndexMaxBits)
        self.dict = {}
        self.table = []
        for i in range(0, 256):
            self.dict[chr(i)] = i
            self.table.append([i])
        self.table.append([])
        self.curPos = 0x0101

    def serialize_key(self, entry):
        return ''.join(map(chr, entry))

    def getIndexOfEntry(self, entry):
        return self.dict.get(self.serialize_key(entry), -1)

    def addEntry(self, entry):
        entry_s = self.serialize_key(entry)
        if self.curPos < self.dicTableLen:
            self.dict[entry_s] = self.curPos
            self.table.append(entry)
            self.curPos += 1
        return self.curPos - 1

    def getEntry(self, pos):
        if pos < self.curPos:
            return self.table[pos]
        return None

    def getCurPos(self):
        return self.curPos

    def getSize(self):
        return self.dicTableLen

    def isFull(self):
        return self.getCurPos() >= self.getSize()

    def getLastEntry(self):
        return self.getEntry(self.getCurPos() - 1)


def encode(inputData, dicIndexMaxBits=0x0B):
    plainData = inputData
    codedData = []
    i = 0
    plainDataLen = len(plainData)
    while i < plainDataLen:
        dic = LZWDictionary(dicIndexMaxBits)
        buff = []
        while i < plainDataLen:
            testChunk = list(buff)
            testChunk.append(plainData[i])
            if dic.getIndexOfEntry(testChunk) != -1:
                buff = testChunk
            else:
                codedData.append(dic.getIndexOfEntry(buff))
                if dic.isFull():
                    break
                dic.addEntry(testChunk)
                buff = [plainData[i]]
            i += 1
        if not dic.isFull():
            codedData.append(dic.getIndexOfEntry(buff))
            i += 1
    return codedData


def ints2bytes(lzwIndexes, mode):
    output = []
    usableBits = 0
    usableBitCount = 0
    indicatorLength = 1
    nextThreshold = 0x0100
    codedCounter = 0
    dicCounter = 0
    remainingIndexesToCode = len(lzwIndexes)

    while remainingIndexesToCode > 0:
        while usableBitCount < 8:
            usableBits |= (lzwIndexes[codedCounter] << usableBitCount)
            codedCounter += 1
            remainingIndexesToCode -= 1
            usableBitCount += (8 + indicatorLength)
            dicCounter += 1
            if dicCounter == nextThreshold:
                dicCounter = 0
                indicatorLength += 1
                nextThreshold <<= 1
                if 8 + indicatorLength > mode:
                    dicCounter = 0
                    indicatorLength = 1
                    nextThreshold = 0x0100
        while usableBitCount >= 8:
            byteToWrite = usableBits & 0xFF
            output.append(byteToWrite)
            usableBits >>= 8
            usableBitCount -= 8
    if usableBitCount > 0:
        output.append(usableBits & 0xFF)
    return output


def compress(data, mode=11):
    enc_data = encode(data)
    return ints2bytes(enc_data, mode)


def decode(inputData, dicIndexMaxBits=0x0B):
    codedData = inputData
    plainData = []
    i = 0
    codedDataLength = len(codedData)

    while i < codedDataLength:
        dic = LZWDictionary(dicIndexMaxBits)
        w = [codedData[i]]
        plainData.append(codedData[i])

        while not dic.isFull() and i < codedDataLength - 1:
            i += 1
            k = codedData[i]
            entry = []
            de = dic.getEntry(k)
            if de is not None:
                entry = de
            elif k == dic.getCurPos():
                entry = w + [w[0]]
            else:
                return plainData
            plainData += entry
            dic.addEntry(w + [entry[0]])
            w = entry
        i += 1
    return plainData


def bytes2ints(b_data, ubyte_mode):
    data = bytearray(b_data)
    remainingCodedBytes = len(data)
    parsedIndexes = []
    usableBits = 0
    usableBitCount = 0
    indicatorLength = 1
    indicatorFlag = 0x001
    nextThreshold = 0x0100
    decodedCounter = 0
    Index = 0

    while remainingCodedBytes > 0:
        while usableBitCount < 8 + indicatorLength:
            usableBits |= (data.pop(0) << usableBitCount)
            remainingCodedBytes -= 1
            usableBitCount += 8
        while usableBitCount >= 8 + indicatorLength:
            Index = usableBits & (((indicatorFlag << 8) & 0xFF00) | 0x00FF)
            usableBits >>= 8
            usableBitCount -= 8
            usableBits >>= indicatorLength
            usableBitCount -= indicatorLength
            decodedCounter += 1
            if decodedCounter == nextThreshold:
                decodedCounter = 0
                indicatorLength += 1
                indicatorFlag <<= 1
                indicatorFlag |= 1
                nextThreshold <<= 1
                if 8 + indicatorLength > ubyte_mode:
                    decodedCounter = 0
                    indicatorLength = 1
                    indicatorFlag = 0x001
                    nextThreshold = 0x0100
            parsedIndexes.append(Index)
    return parsedIndexes


def decompress(data, mode=11):
    lzw_data = bytes2ints(data, mode)
    return decode(lzw_data)
