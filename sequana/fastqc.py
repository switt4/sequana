
import zipfile
import re
from sequana.lazy import pylab
from sequana.lazy import pandas as pd


class FastQC():
    """A temporary class to manipulate fastqc statistics"""

    def __init__(self):

        self.fastqc_data = {}

    def read_sample(self, filename, s_name):
        """reads the fastqc stats

        :param filename:
        :param s_name: sample name. 

        This method was copied from multiqc.modules.fastqc.fastqc modules as a
        temporary hack to read the sample data.
        """
        zz = zipfile.ZipFile(filename)
        file_contents = zz.open("{}{}".format(zz.namelist()[0], "fastqc_data.txt")).read().decode('utf8')

        #self.add_data_source(f, s_name)
        self.fastqc_data[s_name] = { 'statuses': dict() }

        # Here below is the code from  multiqc v1.6
        # Parse the report
        section = None
        s_headers = None
        self.dup_keys = []
        for l in file_contents.splitlines():
            if l == '>>END_MODULE':
                section = None
                s_headers = None
            elif l.startswith('>>'):
                (section, status) = l[2:].split("\t", 1)
                section = section.lower().replace(' ', '_')
                self.fastqc_data[s_name]['statuses'][section] = status
            elif section is not None:
                if l.startswith('#'):
                    s_headers = l[1:].split("\t")
                    # Special case: Total Deduplicated Percentage header line
                    if s_headers[0] == 'Total Deduplicated Percentage':
                        self.fastqc_data[s_name]['basic_statistics'].append({
                            'measure': 'total_deduplicated_percentage',
                            'value': float(s_headers[1])
                        })
                    else:
                      # Special case: Rename dedup header in old versions of
                      # FastQC (v10)
                        if s_headers[1] == 'Relative count':
                            s_headers[1] = 'Percentage of total'
                        s_headers = [s.lower().replace(' ', '_') for s in s_headers]
                        self.fastqc_data[s_name][section] = list()

                elif s_headers is not None:
                    s = l.split("\t")
                    row = dict()
                    for (i, v) in enumerate(s):
                        v.replace('NaN','0')
                        try:
                            v = float(v)
                        except ValueError:
                            pass
                        row[s_headers[i]] = v
                    self.fastqc_data[s_name][section].append(row)
                    # Special case - need to remember order of duplication keys
                    if section == 'sequence_duplication_levels':
                        try:
                            self.dup_keys.append(float(s[0]))
                        except ValueError:
                            self.dup_keys.append(s[0])

        # Tidy up the Basic Stats
        self.fastqc_data[s_name]['basic_statistics'] = {
            d['measure']: d['value'] for d in self.fastqc_data[s_name]['basic_statistics']}

        # Calculate the average sequence length (Basic Statistics gives a range)
        length_bp = 0
        total_count = 0
        for d in self.fastqc_data[s_name].get('sequence_length_distribution', {}):
            length_bp += d['count'] * self._avg_bp_from_range(d['length'])
            total_count += d['count']
        if total_count > 0:
            self.fastqc_data[s_name]['basic_statistics']['avg_sequence_length'] = length_bp / total_count


    def _avg_bp_from_range(self, bp):
        """ Helper function - FastQC often gives base pair ranges (eg. 10-15)
        which are not helpful when plotting. This returns the average from such
        ranges as an int, which is helpful. If not a range, just returns the int
        """
        # copied from multiqc v1.6

        try:
            if '-' in bp:
                maxlen = float(bp.split("-",1)[1])
                minlen = float(bp.split("-",1)[0])
                bp = ((maxlen - minlen)/2) + minlen
        except TypeError:
            pass
        return(int(bp))

    def plot_sequence_quality(self, max_score=40, ax=None):

        for sample in self.fastqc_data.keys():
            data = {self._avg_bp_from_range(d['base']): d['mean']
                for d in self.fastqc_data[sample]['per_base_sequence_quality']}
            df = pd.Series(data)
            df.plot(color="k", alpha=0.5)

        ymax = max_score + 1
        xmax = max(df.index) + 1

        if ax:
            pylab.sca(ax)
        pylab.fill_between([0,xmax], [0,0], [20,20], color='red', alpha=0.4)
        pylab.fill_between([0,xmax], [20,20], [30,30], color='orange', alpha=0.4)
        pylab.fill_between([0,xmax], [30,30], [41,41], color='green',  alpha=0.4)

        X = range(1, xmax + 1)

        #pylab.fill_between(X, 
        #    self.df.mean()+self.df.std(), 
        #    self.df.mean()-self.df.std(), 
        #    color=color, interpolate=False)

        #pylab.plot(X, self.df.mean(), color=color_line, lw=lw)
        pylab.ylim([0, ymax])
        pylab.xlim([0, xmax])
        pylab.title("Quality scores across all bases")
        pylab.xlabel("Position in read (bp)")
        pylab.ylabel("Phred Score", fontsize=12)
        pylab.grid(axis='x')

