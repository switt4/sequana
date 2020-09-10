from sequana import BAM, FastQ
from sequana.lazy import pylab
from sequana.lazy import pandas as pd





def find_motif(bamfile, motif="CAGCAG", window=200, savefig=False, 
    local_th=5, global_th=10):
    """

    If at least 10 position contains at least 5 instances of the motif, then
    this is a hit and the alignment is kept
    """
    b1 = BAM(bamfile)

    # FIND motif and create pictures
    count = 0
    found = []
    Ss = []
    alns = []
    for a in b1:
        count +=1
        if a.query_sequence is None:
            continue
        seq = a.query_sequence
        X1 = [seq[i:i+window].count(motif) for i in range(len(seq))]
        S = sum([x>local_th for x in X1])
        Ss.append(S)
        als.append(a)
        if S > global_th:
            found.append(True)
            off = a.query_alignment_start
            pylab.clf()
            pylab.plot(range(off+a.reference_start, off+a.reference_start+len(seq)),X1)
            if savefig:
                pylab.savefig("{}_{}_{}.png".format(a.reference_name, S, a.query_name.replace("/", "_")))
        else:
            found.append(False)

    return alns, found, Ss




class FindMotif():
    """

        fm = FindMotif("cl10/select1.sorted.bam")
        df = fm.find_motif("CAGCAG")
        df.query("hit>10")

        local threshold should be window length divided by motif length
        divided by 2
    """
    def __init__(self, local_threshold=5, global_threshold=10, window=200):
        self.local_threshold = local_threshold
        self.global_threshold = global_threshold
        self.window = window

    def find_motif_from_sequence(self, seq, motif, window=None,
            local_threshold=None):

        if local_threshold is None:
            local_threshold = self.local_threshold

        if window is None:
            window = self.window

        # This should be improved with a true sliding window
        X1 = [seq[i:i+window].count(motif) for i in range(len(seq))]

        # Number of point crossing the threshold in the sequence
        # The threshold should be below window/len(motif) if there are no errors
        S = sum([x>=local_threshold for x in X1])
        return X1, S

    def find_motif_fasta(self, filename, motif, window=200,
            local_threshold=None, global_threshold=None):
        from sequana import FastA
        data = FastA(filename)
        N = len(data)
        from easydev import Progress
        pb = Progress(N)
        df = {
            "query_name": [],
            "hit": [],
            "length": [],
            "start": [],
            "end": []
        }
        for i, item in enumerate(data):
            X1, S = self.find_motif_from_sequence(item.sequence, motif,
                        window=window, local_threshold=local_threshold
                        )
            if S >= self.global_threshold:
                df['query_name'].append(item.name)
                df['start'].append(0)
                df['end'].append(len(item.sequence))
                df['length'].append(len(item.sequence))
                df['hit'].append(S)
            pb.animate(i+1)
        df = pd.DataFrame(df)
        return df

    def find_motif_bam(self, filename, motif, window=200, figure=False, savefig=False,
            local_threshold=None, global_threshold=None):
        from sequana import BAM
        b1 = BAM(filename)
        df = {
            "query_name": [],
            "hit": [],
            "length": [],
            "start": [],
            "end": []
        }

        for a in b1:
            if a.query_sequence is None:
                continue
            seq = a.query_sequence

            X1, S = self.find_motif_from_sequence(seq, motif, window=window,
                local_threshold=local_threshold)

            df['query_name'].append(a.query_name)
            df['start'].append(a.reference_start)
            df['end'].append(a.reference_end)
            df['length'].append(a.rlen)
            df['hit'].append(S)

            if S >= self.global_threshold:
                off = a.query_alignment_start
                #pylab.clf()
                if figure:
                    pylab.plot(range(off+a.reference_start, off+a.reference_start+len(seq)),X1)
                    if savefig:
                        pylab.savefig("{}_{}_{}.png".format(a.reference_name, S, a.query_name.replace("/", "_")))

        df = pd.DataFrame(df)
        L = len(df.query("hit>5"))
        print(L)
        return df


    def plot_specific_alignment(self, query_name, motif,clf=True,
            windows=[10, 50, 100, 200, 500, 1000]):

        found = None
        bam = BAM(self.bamfile)
        for aln in bam:
            if aln.query_name == query_name:
                found = aln
        if found:
            # Detection
            seq = found.query_sequence
            if clf:pylab.clf()
            for window in windows:
                X = [seq[i:i+window].count(motif) for i in range(len(seq))]
                pylab.plot(X, label=window)
                score = sum([x>window/6 for x in X])
                print(window, score/3.)
            pylab.legend()
            pylab.ylabel("# {} in a given sliding window".format(motif))
            pylab.title(query_name)
        else:
            print("Not found")

    """def find_length(self, query_name, motif, window=200):
        found = None
        bam = BAM(self.bamfile)
        for aln in bam:
            if aln.query_name == query_name:
                found = aln
        if found:
            # Detection
            seq = found.query_sequence
            if clf:pylab.clf()
            for window in windows:
    """

    def _get_aligments(self, motif, window=200, global_th=10):
        df = self.find_motif(motif=motif, window=window)
        df = df.query("hit>@global_th")
        return df

    def plot_alignment(self, motif, window=200,
            global_th=10,title=None,legend=True, legend_fontsize=11):
        """


        plot alignments that match the motif. 

        """
        df = self._get_aligments(motif=motif, window=window, global_th=global_th)
        print("Found {} hits".format(len(df)))
        bam = BAM(self.bamfile)
        pylab.clf()
        count = 0
        for aln in bam:
            if aln.query_name in df.query_name.values:
                seq = aln.query_sequence
                if seq:
                    count += 1
                    X1 = [seq[i:i+window].count(motif) for i in range(len(seq))]
                    pylab.plot(range(aln.reference_start,
                        aln.reference_start+len(seq)),X1, label=aln.query_name)

        max_theo = int(1.2*window / len(motif))
        pylab.ylim([0, max_theo])
        if legend and count<15:
            pylab.legend(fontsize=legend_fontsize)
        if title:
            pylab.title(title, fontsize=16)

        return df










