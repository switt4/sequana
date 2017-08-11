"""Utilities to manipulate FASTQ and Reads

"""
import io
import time
import zlib
from itertools import islice
import gzip
import subprocess
from functools import wraps

from sequana.lazy import numpy as np
from sequana.lazy import pandas as pd
from sequana.lazy import pylab

from easydev import Progress

import pysam
try:
    from itertools import izip_longest
except:
    from itertools import zip_longest as izip_longest

# for filter fastq files. see below in FastQ for the usage
# we want to take 4 lines at a time (assuming there is no empty lines)
def grouper(iterable):
    args = [iter(iterable)] * 4
    return izip_longest(*args)


__all__ = ["Identifier", "FastQ", "FastQC"]


class Identifier(object):
    """Class to interpret Read's identifier

    .. warning:: Implemented for Illumina 1.8+  and 1.4 . Other cases
        will simply stored the identifier without interpretation

    .. doctest::

        >>> from sequana import Identifier
        >>> ident = Identifier('@EAS139:136:FC706VJ:2:2104:15343:197393 1:Y:18:ATCACG')
        >>> ident.info['x_coordinate']
        '15343'

    Currently, the following identifiers will be recognised automatically:

    :Illumina_1_4: An example is ::

          @HWUSI-EAS100R:6:73:941:1973#0/1

    :Illumina_1_8: An example is::

        @EAS139:136:FC706VJ:2:2104:15343:197393 1:Y:18:ATCACG


    Other that could be implemented are NCBI ::

        @FSRRS4401BE7HA [length=395] [gc=36.46] [flows=800] [phred_min=0] \
                                           [phred_max=40] [trimmed_length=95]

    Information can also be found here http://support.illumina.com/help/SequencingAnalysisWorkflow/Content/Vault/Informatics/Sequencing_Analysis/CASAVA/swSEQ_mCA_FASTQFiles.htm
    """
    def __init__(self, identifier, version="unknown"):
        self.identifier = identifier[:]

        if version == "Illumina_1.8+":
            info = self._interpret_illumina_1_8()
        elif version == "Illumina_1.4+":
            info = self._interpret_illumina_1_4()
        else:
            try:
                info = self._interpret_illumina_1_8()
                version = "Illumina_1.8+"
            except:
                try:
                    info = self._interpret_illumina_1_4()
                    version = "Illumina_1.4+"
                except:
                    info = self.identifier[:]
        self.info = info
        self.version = version

    def _interpret_illumina_1_8(self):
        """

        @EAS139:136:FC706VJ:2:2104:15343:197393 1:Y:18:ATCACG

        Note the space and : separators
        """
        assert self.identifier.startswith(b"@")
        # skip @ character
        identifier = self.identifier[1:]
        # replace spaces by : character
        identifier = b' '.join(identifier.split())
        identifier = identifier.replace(b' ', b':')
        items = identifier.split(b':')
        if len(items) != 11:
            raise ValueError('Number of items in the identifier should be 11')
        res = {}
        res['identifier'] = self.identifier[:]
        res['instrument'] = items[0]
        res['run_id'] = items[1]
        res['flowcell_id'] = items[2]
        res['flowcell_lane'] = items[3]
        res['tile_number'] = items[4]
        res['x_coordinate'] = items[5]
        res['y_coordinate'] = items[6]
        res['member_pair'] = items[7]
        res['filtered'] = items[8]
        res['control_bits'] = items[9]
        res['index_sequence'] = items[10]
        res['version'] = 'Illumina_1.8+'
        return res

    def _interpret_illumina_1_4(self):
        # skip @ character
        identifier = self.identifier[1:]
        identifier = identifier.replace('#', ':')
        identifier = identifier.replace('/', ':')
        items = identifier.split(':')

        # ['@HWUSI-EAS100R', '6', '73', '941', '1973#0/1']
        res = {}
        res['identifier'] = self.identifier[:]
        res['instrument_name'] = items[0]
        res['flowcell_lane'] = items[1]
        res['tile_number'] = items[2]
        res['x_coordinate'] = items[3]
        res['y_coordinate'] = items[4]
        res['index'] = '#' + items[5]
        res['member_pair'] = items[6]
        res['version'] = 'Illumina_1.4+'
        return res

    def __str__(self):
        txt = ""
        for key in sorted(self.info.keys()):
            txt += '%s: %s\n' % (key, self.info[key])
        return txt

    def __repr__(self):
        return "Identifier (%s)" % self.version


class FastQ(object):
    """Class to handle FastQ files

    Some of the methods are based on pysam but a few are also
    original to sequana. In general, input can be zipped ot not and
    output can be zipped or not (based on the extension).

    An example is the :meth:`extract_head` method::

        f = FastQ("input_file.fastq.gz")
        f.extract_head(100000, output='test.fastq')
        f.extract_head(100000, output='test.fastq.gz')

    equivalent to::

        zcat myreads.fastq.gz | head -100000 | gzip > test100k.fastq.gz

    An efficient implementation to count the number of lines is also available::

        f.count_lines()

    or reads (assuming 4 lines per read)::

        f.count_reads()

    Operators available:

        - equality ==
    """

    """
    Features to implement::
        - filter out short / long reads
        - filter out reads with NNN
        - filter out low quality end reads
        - cut poly A/T tails
        - dereplicate sequences
        - split multiplex
        - remove contaminants
        - compact fastq
        - convert to/from sff

    """
    _N = 4
    def __init__(self, filename, verbose=False):

        self.filename = filename
        self.verbose = verbose
        self._count_reads = None
        self._count_lines = None

        # opens the file in read mode
        self.__enter__()
        # Can we identify the type of data ?
        try:
            self.identifier = Identifier(self.next()["identifier"])
            self.rewind()
            self.data_format = self.identifier.version
        except:
            self.data_format = "unknown"

    def _get_count_reads(self):
        if self._count_reads is None:
            self._count_reads = self.count_reads()
        return self._count_reads
    n_reads = property(_get_count_reads, doc="return number of reads")

    def _get_count_lines(self):
        if self._count_lines is None:
            self._count_lines = self.count_lines()
        return self._count_lines
    n_lines = property(_get_count_lines,
        doc="return number of lines (should be 4 times number of reads)")

    def __len__(self):
        return self.n_reads

    def rewind(self):
        """Allows to iter from the beginning without openning the file or
        creating a new instance.

        """
        nreads = self._count_reads
        self._fileobj.close()
        self.__enter__()
        self._count_reads = nreads

    def _count_lines_gz(self, CHUNKSIZE=65536):
        # this is fast. On a 63M reads, takes 21 seconds as
        # compared to 46 s (real) and 1.13 (user) with zcat | wc
        # wc seems slow (same effects with uncompressde file).
        # Using gzip.open and reading lines is slower by a factor 10
        # hints from http://wiki.glitchdata.com/index.php?title=Python:_File_Compression_and_Decompression

        # cannot be re-used so must be written here and wherever decompression is
        # required
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        with open(self.filename, 'rb') as f:
            buf = f.read(CHUNKSIZE)
            count = 0
            while buf:
                outstr = d.decompress(buf)
                count += outstr.count(b"\n")
                buf = f.read(CHUNKSIZE)
        return count

    def count_lines(self):
        """Return number of lines

        This is 10-20 times faster than *wc* on uncompressed file and
        3-4 times faster on zipped file (using gunzip -c file | wc -l)
        """
        if self.filename.endswith("gz"):
            count = self._count_lines_gz()
        else:
            count = self._count_reads_buf()
        return count

    def count_reads(self):
        """Return count_lines divided by 4"""
        nlines = self.count_lines()
        if divmod(nlines, self._N)[1] != 0:
            print("WARNING. number of lines not multiple of 4.")
        return int(nlines / self._N)

    def _count_reads_buf(self, block=1024*1024):
        # 0.12 seconds to read 3.4M lines, faster than wc command
        # on 2M reads, takes 0.1 seconds whereas wc takes 1.2 seconds
        lines = 0
        with open(self.filename, 'rb') as f:
            buf = f.read(block)
            while buf:
                lines += buf.count(b'\n')
                buf = f.read(block)
        return lines

    def extract_head(self, N, output_filename):
        """Extract the heads of a FastQ files

        :param int N:
        :param str output_filename: Based on the extension
            the output file is zipped or not (.gz extension only)

        This function is convenient since it takes into account
        the input file being compressed or not and the output file
        being compressed ot not. It is in general 2-3 times faster than the
        equivalent unix commands combined together but is 10 times
        slower for the case on uncompressed input and uncompressed output.

        .. warning:: this function extract the N first lines and does not check
            if there are empty lines in your FastQ/FastA files.
        """
        if self.filename.endswith(".gz"):
            self._extract_head_gz(N, output_filename)
        else:
            self._extract_head(N, output_filename)

    def _extract_head(self, N, output_filename):
        with open(self.filename, 'r') as fin:
            if output_filename.endswith("gz"):
                output_filename_nogz = output_filename.replace(".gz", "")

                with open(output_filename_nogz, 'w') as fout:
                    fout.writelines(islice(fin, N))

                # compress the file
                self._gzip(output_filename_nogz)

            else:
                with open(output_filename, 'w') as fout:
                    fout.writelines(islice(fin, N))

    def _gzip(self, filename):
        try:
            s = subprocess.Popen(["pigz", "-f", filename])
            s.wait()
        except:
            s = subprocess.Popen(["gzip", filename, "-f"])
            s.wait()

    def _extract_head_gz(self, N, output_filename="test.fastq.gz", level=6, CHUNKSIZE=65536):
        """

        If input is compressed:

            if output not compressed, this is 20% faster than
            "zcat file | head -1000000 > output.fastq

            If output is compressed, this is 3-4 times faster than :
            "zcat file | head -1000000 | gzip > output.fastq

        If input is compressed:

            if output not compressed, this is 10 times slower than
            "head -1000000 > output.fastq

            If output is compressed, this is 3-4 times faster than :
            "head -1000000 | gzip > output.fastq

        Tested with Python 3.5 , Linux box.
        """
        # make sure N is integer
        N = int(N)

        # as fast as zcat file.fastq.gz | head -200000 > out.fasta

        # this is to supress the header
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)

        # will we gzip the output file ?
        output_filename, tozip = self._istozip(output_filename)

        with open(self.filename, 'rb') as fin:
            buf = fin.read(CHUNKSIZE)
            count = 0

            with open(output_filename, "wb") as fout:
                while buf:
                    outstr = d.decompress(buf)
                    this_count = outstr.count(b"\n")

                    if count + this_count > N:
                        # there will be too many lines, we need to select a subset
                        missing = N - count
                        outstr = outstr.strip().split(b"\n")
                        outstr = b"\n".join(outstr[0:missing]) + b"\n"
                        fout.write(outstr)
                        break
                    else:
                        count += this_count
                    fout.write(outstr)
                    buf = fin.read(CHUNKSIZE)

        if tozip is True: self._gzip(output_filename)
        return count

    def _istozip(self, filename):
        if filename.endswith('.gz'):
            tozip = True
            filename = filename.split(".gz",1)[0]
        else:
            tozip = False
        return filename, tozip

    def select_random_reads(self, N=None, output_filename="random.fastq"):
        """Select random reads and save in a file

        :param int N: number of random unique reads to select
            should provide a number but a list can be used as well. 
            You can select random reads for R1, and re-use the returned list as
            input for the R2 (since pairs must be kept)
        :param str output_filename:

        If you have a pair of files, the same reads must be selected in R1 and
        R2.::

            f1 = FastQ(file1)
            selection = f1.select_random_reads(N=1000)
            f2 = FastQ(file2)
            f2.select_random_reads(selection)


        """
        thisN = len(self)
        if isinstance(N, int):
            if N > thisN:
                N = thisN
            # create random set of reads to pick up
            cherries = list(range(thisN))
            np.random.shuffle(cherries)
            # cast to set for efficient iteration
            cherries = set(cherries[0:N])
        elif isinstance(N, set):
            cherries = N
        elif isinstance(N, list):
            cherries = set(N)

        fastq = pysam.FastxFile(self.filename)


        pb = Progress(thisN) # since we scan the entire file
        with open(output_filename, "w") as fh:
            for i, read in enumerate(fastq):
                if i in cherries:
                    fh.write(read.__str__() + "\n")
                else:
                    pass
                pb.animate(i+1)
        return cherries

    def split_lines(self, N=100000, gzip=True):
        """Not implemented"""
        if self.filename.endswith(".gz"):
            outputs = self._split_lines_gz(N, gzip=gzip)
        else:
            outputs = self._split_lines(N, gzip=gzip)
        return outputs

    def _split_lines_gz(self, N, gzip=True, CHUNKSIZE=65536):
        # split input in N files
        # There is a split function under Unix but (1) not under windows
        # and (2) split a gzip into N chunks or n lines will split the
        # reads in the middle. So, we want to unzip, select N lines (or chunks)
        # and zip each chunk.
        self._check_multiple(N)
        N_chunk, remainder = divmod(self.n_lines, N)
        if remainder > 0:
            N_chunk += 1

        # let prepare some data first. Let us build the filenames once for all
        outputs = []
        for i in range(0, N_chunk):
            lb = (i ) * N + 1
            ub = (i + 1) * N
            if ub > self.n_lines:
                ub = self.n_lines

            if self.filename.endswith(".gz"):
                input_filename = self.filename.split(".gz")[0]
                output_filename = input_filename
            else:
                input_filename = self.filename
                output_filename = self.filename
            output_filename.split(".", -1)
            left, right = input_filename.rsplit(".", 1)
            output_filename = left + "_%s_%s." % (lb, ub) + right
            outputs.append(output_filename)

        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        with open(self.filename, 'rb') as fin:
            # init buffer
            buf = fin.read(CHUNKSIZE)
            count = 0

            # open an output file handler
            current_file_counter = 0
            fout = open(outputs[0], "wb")

            while buf:
                outstr = d.decompress(buf)
                count += outstr.count(b"\n")
                if count > N:
                    # if too many lines were read, fill the current file
                    # and keep remaining data (skip the reading of new
                    # data for now)
                    missing = count - N
                    outstr = outstr.strip().split(b"\n")
                    NN = len(outstr)
                    # we need to split the buffer into the part to save
                    # in this file and the part to save in the next file later
                    # on (remaining)
                    # Note that there is no '\n' added here because we do not
                    # read lines that we may end up in the middle of a line
                    remaining  = b"\n".join(outstr[NN-missing-1:])
                    # whereas here, we are at the end of a line
                    outstr = b"\n".join(outstr[0:NN-missing-1]) + b"\n"
                    # write and close that file
                    fout.write(outstr)
                    fout.close()
                    # and open the next one where we can already save the end of
                    # the buffer
                    current_file_counter += 1
                    fout = open(outputs[current_file_counter], "wb")
                    fout.write(remaining)
                    # we need to keep track of what has be written
                    count = remaining.count(b'\n')
                    # and finally we can now read a new chunk of data
                    buf = fin.read(CHUNKSIZE)
                else:
                    fout.write(outstr)
                    buf = fin.read(CHUNKSIZE)

        if gzip is True:
            for output in outputs:
                self._gzip(output)
            outputs = [x + ".gz" for x in outputs]
        return outputs

    def _split_chunks(self, N=10):
        # split per chunks of size N
        pass

    def _check_multiple(self, N, multiple=4):
        if divmod(N, multiple)[1] != 0:
            msg = "split_lines method expects a multiple of %s." %multiple
            raise ValueError(msg)

    # This could be part of easydev or other software
    # we could also use a unix command but won't work on other platforms
    def _split_lines(self, N, gzip=True):
        # split input in N files
        # We will name them with reads number that is
        # filename.fastq gives for example:
        # --> filename_1_100000.fastq
        # --> filename_100001_151234.fastq
        self._check_multiple(N)

        assert type(N) == int
        if N >= self.n_lines:
            print("Nothing to do. Choose a lower N value")
            return

        outputs = []
        N_chunk, remainder = divmod(self.n_lines, N)

        with open(self.filename) as fin:
            for i in range(0, N_chunk):
                lb = (i ) * N + 1
                ub = (i + 1) * N
                output_filename = self.filename
                output_filename.split(".", -1)
                left, right = self.filename.rsplit(".", 1)
                output_filename = left + "_%s_%s." % (lb, ub) + right
                outputs.append(output_filename)
                with open(output_filename, 'w') as fout:
                    fout.writelines(islice(fin, N))
            # last chunk is dealt with outside the loop
            lb = ub + 1
            ub = self.n_lines
            output_filename = left + "_%s_%s." % (lb, ub) + right
            if remainder !=0:
                outputs.append(output_filename)
                with open(output_filename, 'w') as fout:
                    fout.writelines(islice(fin, remainder))

        if gzip is True:
            for output in outputs:
                self._gzip(output)
            outputs = [x + ".gz" for x in outputs]
        return outputs

    def split_chunks(self, N=10):
        """Not implemented"""
        assert N <=100, "you cannot split a file into more than 100 chunks"
        # split per chunks of size N
        cmd = "split --number %s %s -d"

    """def random(self, N=10000, output_filename="test.fastq",
               bp=50, quality=40):
        # a completely random fastq
        from .phred import quality
        with open(output_filename, "wb") as fh:
            count = 1
            template = "@Insilico\n"
            template += "%(sequence)\n"
            template += "+\n"
            template += "%s(quality)\n"
            fh.writelines(template % {
                'sequence': "".join(["ACGT"[random.randint(0,3)] for this in range(bp)]),
                'quality': "".join()})
        # quality could be q function for a distribution
    """
    def joining(self, pattern, output_filename):
        """not implemented

        zcat Block*.fastq.gz | gzip > combined.fastq.gz

        """
        raise NotImplementedError

    def __iter__(self):
       return self

    def __exit__(self, type, value, traceback):
        try:
            self._fileobj.close()
        except AttributeError:
            pass
        finally:
            self._fileobj.close()

    def __enter__(self):
        fh = open(self.filename, "rb")
        if self.filename.endswith('.gz'):
            self._fileobj = gzip.GzipFile(fileobj=fh)
        else:
            self._fileobj = fh
        return self

    def __next__(self): # python 3
        return self.next()

    def next(self): # python 2
        # reads 4 lines
        d = {'quality':None, 'sequence': None, 'quality':None}
        try:
            """data = islice(self._fileobj, 4)
            d['identifier'] = next(data).strip()
            d['sequence'] = next(data).strip()
            skip = next(data)
            d['quality'] = next(data).strip()
            """

            # 15% faster than islice + next
            d['identifier'] = self._fileobj.readline().strip()
            d['sequence'] = self._fileobj.readline().strip()
            temp = self._fileobj.readline()
            d['quality'] = self._fileobj.readline().strip()

            # can be faster but slower on average
            """d['identifier'] = self._fileobj.readlines(1)[0].strip()
            d['sequence'] = self._fileobj.readlines(1)[0].strip()
            self._fileobj.readlines(1)
            d['quality'] = self._fileobj.readlines(1)[0].strip()
            """
            # Somehow the readlines still return "" even if the end of file is
            # reached
            if temp == b"":
                raise StopIteration
        except KeyboardInterrupt:
            # THis should allow developers to break an function that iterates
            # through the read to run forever
            self._fileobj.close()
            self.__enter__()
        except:
            self.rewind()
            raise StopIteration

        return d

    def __getitem__(self, index):
        return 1

    def _to_fasta(self, output_filename="test.fasta", level=6, CHUNKSIZE=65536):
        """

        """
        raise NotImplementedError
        """
        #twice as slow as a tool such as seqtk and final fasta number not correct...
        # this is to supress the header
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)

        # will we gzip the output file ?
        output_filename, tozip = self._istozip(output_filename)

        with open(self.filename, 'rb') as fin:
            buf = fin.read(CHUNKSIZE)

            count = 0
            with open(output_filename, "wb") as fout:
                while buf:
                    outstr = d.decompress(buf)
                    lines = outstr.strip().split(b"\n")
                    for line in lines:
                        if count%4 == 0:
                            fout.write(b">"+line[1:]+b"\n")
                        elif count%4==1:
                            fout.write(line+b"\n")
                        count += 1

                    buf = fin.read(CHUNKSIZE)

        if tozip is True: self._gzip(output_filename)
        """
    def filter(self, identifiers_list=[], min_bp=None, max_bp=None,
        progressbar=True, output_filename='filtered.fastq', remove=True):
        """Filter reads

        :param int min_bp: ignore reads with length shorter than min_bp
        :param int max_bp: ignore reads with length above max_bp

        """
        # 7 seconds without identifiers to scan the file
        # on a 750000 reads

        if min_bp is None:
            min_bp = 0

        if max_bp is None:
            max_bp = 1e9

        # make sure we are at the beginning
        self.rewind()

        output_filename, tozip = self._istozip(output_filename)

        with open(output_filename, "w") as fout:
            pb = Progress(self.n_reads)
            buf = ""
            filtered = 0

            for count, lines in enumerate(grouper(self._fileobj)):
                identifier = lines[0].split()[0]
                if lines[0].split()[0] in identifiers_list:
                    filtered += 1
                else:
                    N = len(lines[1])
                    if N <= max_bp and N >= min_bp:
                        buf += "{}{}+\n{}".format(
                            lines[0].decode("utf-8"),
                            lines[1].decode("utf-8"),
                            lines[3].decode("utf-8"))
                    if count % 100000 == 0:
                        fout.write(buf)
                        buf = ""
                if progressbar is True:
                    pb.animate(count+1)
            fout.write(buf)
            if filtered < len(identifiers_list):
                print("\nWARNING: not all identifiers were found in the fastq file to " +
                      "be filtered.")
        if tozip is True: self._gzip(output_filename)

    def to_kmer_content(self, k=7):
        """Return a Series with kmer count across all reads

        :param int k: (default to 7-mers)
        :return: Pandas Series with index as kmer and values as count.

        Takes about 30 seconds on a million reads.
        """
        # Counter is slow if we apply it on each read.
        # .count is slow as well
        import collections
        from sequana.kmer import get_kmer
        counter = collections.Counter()
        pb = Progress(len(self))
        buffer_ = []
        for i, this in enumerate(self):
            buffer_.extend(list(get_kmer(this['sequence'], k)))
            if len(buffer_) > 100000:
                counter += collections.Counter(buffer_)
                buffer_ = []
            pb.animate(i)
        counter += collections.Counter(buffer_)

        ts = pd.Series(counter)
        ts.sort_values(inplace=True, ascending=False)

        return ts

    def to_krona(self, k=7, output_filename="fastq.krona"):
        """Save Krona file with ACGT content within all k-mers

        :param int k: (default to 7-mers)

        Save results in file, which can then be translated into a HTML file
        using::

            ktImportText fastq.krona 
            open text.krona.html

        """
        ts = self.to_kmer_content(k=k)

        with open(output_filename, "w") as fout:
            for index, count in ts.items():
                letters = "\t".join([x for x in index.decode()])
                fout.write("%s\t" % count + letters + "\n")

    def __eq__(self, other):
        if id(other) == id(self):
            return True
        self.rewind()
        other.rewind()
        for this in self:
            if this != other.next():
                return False
        return True


# a simple decorator to check whether the data was computed or not.
# If not, compute it
def run_info(f):
    @wraps(f)
    def wrapper(*args, **kargs):
        #args[0] is the self of the method
        try:
            args[0].gc_content
        except:
            args[0]._get_info()
        return f(*args, **kargs)
    return wrapper


class FastQC(object):
    """Simple QC diagnostic


    Similarly to some of the plots of FastQC tools, we scan the
    FastQ and generates some diagnostic plots. The interest
    is that we'll be able to create more advanced plots later on.

    Here is an example of the boxplot quality across all bases:

    .. plot::
        :include-source:

        from sequana import sequana_data
        from sequana import FastQC
        filename  = sequana_data("test.fastq", "testing")
        qc = FastQC(filename)
        qc.boxplot_quality()

    .. warning:: some plots will work for Illumina reads only right now

    .. note:: Although all reads are parsed (e.g. to count the number of
        nucleotides, some information uses a limited number of reads (e.g.
        qualities), which is set to 500,000 by deafult.


    """
    def __init__(self, filename, max_sample=500000, dotile=False, verbose=True):
        """.. rubric:: constructor

        :param filename:
        :param int max_sample: Large files will npt fit in memory. We therefore
            restrict the numbers of reads to be used for some of the statistics
            to 500,000.  This also reduces the amount of time required to get a
            good feeling of the data quality. The entire input file is
            parsed tough. This is required for instance to get the number of
            nucleotides.
        :param bool dotile: compute more
        """
        self.verbose = verbose
        self.filename = filename

        # Later we will use pysam to scan the fastq because
        # it iterate quickly while providing the quality already converted
        # However, the FastQ implementation in this module is faster at
        # computing the lentgth by a factor 3
        self.fastq = FastQ(filename)
        self.N = len(self.fastq)

        # Use only max_sample in some of the computation
        self.max_sample = min(max_sample, self.N)

        self.dotile = dotile

        self.summary = {}
        self.fontsize = 16

    def _get_info(self):
        """Populates the data structures for plotting.

        Will be called on request"""
        qualities = []
        mean_qualities = []
        sequences = []
        minimum = 1e6
        maximum = 0
        self.lengths = np.empty(self.N)
        self.gc_list = []
        self.N_list = []

        self.identifiers = []
        if self.verbose:
            pb = Progress(self.N)

        # could use multiprocessing
        fastq = pysam.FastxFile(self.filename)
        for i, record in enumerate(fastq):
            try:
                self.lengths[i] = len(record.sequence)
            except:
                print(record)

            if i < self.max_sample:
                quality = record.get_quality_array()
                mean_qualities.append(sum(quality)/self.lengths[i])
                qualities.append(quality)
                sequences.append(record.sequence)

            if self.dotile:
                identifier = Identifier(record.name)
                self.identifiers.append(identifier.info)

            GC = record.sequence.count('G') + record.sequence.count('C')
            self.gc_list.append(GC/float(self.lengths[i])*100)
            self.N_list.append(record.sequence.count('N'))

            if self.verbose:
                pb.animate(i+1)

        # other data
        self.qualities = qualities
        self.mean_qualities = mean_qualities
        self.minimum = int(self.lengths.min())
        self.maximum = int(self.lengths.max())
        self.sequences = sequences
        self.nucleotides = self.lengths.sum()
        self.gc_content = np.mean(self.gc_list)

        try:
            if self.dotile:
                print('\nCreating tiles data')
                self.tiles = {}
                self.tiles['x'] = [float(this['x_coordinate']) for this in self.identifiers]
                self.tiles['y'] = [float(this['y_coordinate']) for this in self.identifiers]
                self.tiles['tiles'] = [this['tile_number'] for this in self.identifiers]
                import collections
                d = collections.defaultdict(list)
                for tile, seq in zip(self.tiles['tiles'], self.qualities):
                    d[tile].append(seq)
                self.data_imqual = [pd.DataFrame(d[key]).mean().values for key in sorted(d.keys())]
        except:
            print("Some data could not be extracted from identifiers. "
            "Not all figure will be available. Illumina identifiers required")

    @run_info
    def imshow_qualities(self):
        """Qualities

        ::

            from sequana import sequana_data
            from sequana import FastQC
            filename  = sequana_data("test.fastq", "testing")
            qc = FastQC(filename)
            qc.imshow_qualities()
            from pylab import tight_layout; tight_layout()

        """
        from biokit.viz import Imshow
        im = Imshow(self.data_imqual)
        im.plot(xticks_on=False, yticks_on=False, origin='lower')
        pylab.title("Quality per tile", fontsize=self.fontsize)
        pylab.xlabel("Position in read (bp)")
        pylab.ylabel("tile number")

    @run_info
    def boxplot_quality(self, hold=False, ax=None):
        """Boxplot quality

        Same plots as in FastQC that is average quality for all bases.
        In addition a 1 sigma error enveloppe is shown (yellow).

        Background separate zone of good, average and bad quality (arbitrary).


        """
        df = pd.DataFrame(self.qualities)
        from biokit.viz.boxplot import Boxplot
        bx = Boxplot(df)
        try:
            # new version of biokit
            bx.plot(ax=ax)
        except:
            bx.plot()

    @run_info
    def histogram_sequence_coordinates(self):
        """Histogram of the sequence coordinates on the plate

        ::

            from sequana import sequana_data
            from sequana import FastQC
            filename  = sequana_data("test.fastq", "testing")
            qc = FastQC(filename)
            qc.histogram_sequence_coordinates()

        .. note:: in this data set all points have the same coordinates.

        """
        # Distribution of the reads in x-y plane
        # less reads on the borders ?
        from biokit.viz.hist2d import Hist2D
        Hist2D(self.tiles['x'], self.tiles['y']).plot()

    @run_info
    def histogram_sequence_lengths(self, logy=True):
        """Histogram sequence lengths

        .. plot::
            :include-source:

            from sequana import sequana_data
            from sequana import FastQC
            filename  = sequana_data("test.fastq", "testing")
            qc = FastQC(filename)
            qc.histogram_sequence_lengths()

        """
        data = [len(x) for x in self.sequences]
        bary, barx = np.histogram(data, bins=range(max(data)+1))

        # get rid of zeros to avoid warnings
        bx = [x for x,y in zip(barx, bary) if y!=0]
        by = [y for x,y in zip(barx, bary) if y!=0]
        if logy:
            pylab.bar(bx, pylab.log10(by))
        else:
            pylab.bar(bx, by)

        pylab.xlim([1,max(data)+1])

        pylab.grid(True)
        pylab.xlabel("position (bp)", fontsize=self.fontsize)
        pylab.ylabel("Count (log scale)", fontsize=self.fontsize)

    @run_info
    def histogram_gc_content(self):
        """Plot histogram of GC content

        .. plot::
            :include-source:

            from sequana import sequana_data
            from sequana import FastQC
            filename  = sequana_data("test.fastq", "testing")
            qc = FastQC(filename)
            qc.histogram_gc_content()

        """
        pylab.hist(self.gc_list, bins=range(0, 100))
        pylab.grid()
        pylab.title("GC content distribution (per sequence)")
        pylab.xlabel(r"Mean GC content (%)", fontsize=self.fontsize)
        pylab.xlim([0,100])

    @run_info
    def get_stats(self):
        stats = {"GC content": self.gc_content,
            "n_reads": self.N}
        for letter in 'ACGTN':
            stats[letter] = sum((x.count(letter) for x in self.sequences))

        stats['total bases'] = sum([len(this) for this in self.sequences])
        stats['mean quality'] = np.mean(self.mean_qualities)
        stats['average read length'] = np.mean([len(this) for this in self.sequences])
        stats['min read length'] = np.min([len(this) for this in self.sequences])
        stats['max read length'] = np.max([len(this) for this in self.sequences])

        # use DataFrame instead of Series to mix types (int/float)
        ts = pd.DataFrame([stats])
        cols = ['n_reads', 'A', 'C', 'G', 'T', 'N','total bases' ]
        ts[cols] = ts[cols].astype(int)
        ts = ts[cols + ['GC content', 'average read length', 'mean quality']]
        return ts

    @run_info
    def get_actg_content(self):

        # Assuming length of the reads are all equal !
        N = len(self.sequences[0])
        Total = float(len(self.sequences))

        Nseq = len(self.sequences)
        from collections import Counter
        data = []
        for pos in range(N):
            data.append(Counter([self.sequences[i][pos] for i in range(Nseq)]))

        df = pd.DataFrame.from_records(data)
        df /= Total
        if "N" in df.columns:
            df = df[["A", "C", "G", "T", "N"]]
        else:
            df = df[["A", "C", "G", "T"]]
        return df

    def plot_acgt_content(self):
        """Plot histogram of GC content

        .. plot::
            :include-source:

            from sequana import sequana_data
            from sequana import FastQC
            filename  = sequana_data("test.fastq", "testing")
            qc = FastQC(filename)
            qc.plot_acgt_content()
        """
        df = self.get_actg_content()
        df.plot()
        pylab.grid(True)
        pylab.xlabel("position (bp)", fontsize=self.fontsize)
        pylab.ylabel("percent", fontsize=self.fontsize)

