# -*- coding: utf-8 -*-
#
#  This file is part of Sequana software
#
#  Copyright (c) 2016 - Sequana Development Team
#
#  File author(s):
#      Thomas Cokelaer <thomas.cokelaer@pasteur.fr>
#      Dimitri Desvillechabrol <dimitri.desvillechabrol@pasteur.fr>, 
#          <d.desvillechabrol@gmail.com>
#
#  Distributed under the terms of the 3-clause BSD license.
#  The full license is in the LICENSE file, distributed with this software.
#
#  website: https://github.com/sequana/sequana
#  documentation: http://sequana.readthedocs.io
#
##############################################################################
"""Analysis of VCF file generated by freebayes.

"""

import sys

import vcf
import pandas as pd


class VCF(vcf.Reader):
    """VCF class (Variant Calling Format)

    This class is a wrapping of vcf.Reader class from the pyVCF package

    ::

        from sequana import sequana_data, VCF
        vcf_filename = sequana_data("test.vcf", "testing")

        # Read the data
        v = VCF(vcf_filename)

        # Filter the data
        filter_dict = {"QUAL": 10000, "FREQ": 0.85, 
            "INFO": {"DP": ">10", "AO": ">200", "SRP": "<100"}}
        v.filter_vcf(filter_dict, "output.vcf")

    """
    def __init__(self, filename, **kwargs):
        """
        Filter vcf file with a dictionnary.

        :param str filename: a vcf file.
        :param kwargs: any arguments accepted by vcf.Reader
        """
        try:
            self.filename = filename
            filin = open(filename, "r")
            vcf.Reader.__init__(self, fsock=filin, **kwargs)
            self._get_start_index()
            self._vcf_to_df()
        except IOError as e:
            print("I/O error({0}): {1}".format(e.errno, e.strerror))

    def _get_start_index(self):
        self._reader.seek(0)
        for line in iter(self._reader.readline, ''):
            if line.startswith("#"):
                self.start_index = self._reader.tell()
            else:
                break

    def _strand_rate(self, number1, number2):
        try:
            division = float(number1) / (number1 + number2)
        except ZeroDivisionError:
            return 0
        return division

    def _compute_freq(self, vcf_line):
        alt_freq = [float(count)/vcf_line.INFO["DP"] for count in \
                vcf_line.INFO["AO"]]
        return alt_freq

    def _compute_strand_bal(self, vcf_line):
        strand_bal = [self._strand_rate(vcf_line.INFO["SAF"][i], 
            vcf_line.INFO["SAR"][i]) for i in range(len(vcf_line.INFO["SAF"]))]
        return strand_bal

    def _filter_info_field(self, info_value, threshold):
        if(threshold.startswith("<")):
            if(threshold.startswith("<=")):
                if(info_value <= int(threshold[2:])):
                    return False
            elif(info_value < int(threshold[1:])):
                return False
        else:
            if(threshold.startswith(">=")):
                if(info_value >= int(threshold[2:])):
                    return False
            elif(info_value > int(threshold[1:])):
                return False
        return True

    def _filter_line(self, vcf_line, filter_dict):
        # dictionary must have QUAL/FREQ/INFO keys

        if(vcf_line.QUAL < filter_dict["QUAL"]):
            return False
        
        alt_freq = self._compute_freq(vcf_line)
        strand_bal = self._compute_strand_bal(vcf_line)
        if(alt_freq[0] < filter_dict["FREQ"]):
            return False

        for key, value in filter_dict["INFO"].items():
            try:
                if(type(vcf_line.INFO[key]) != list):
                    if(self._filter_info_field(vcf_line.INFO[key], value)):
                        return False
                else:
                    if(self._filter_info_field(vcf_line.INFO[key][0], value)):
                        return False
            except KeyError:
                print("The key {0} does not exist in VCF file".format(key))
                print("Please, remove it in your config file")
                sys.exit(1)
        return True

    def filter_vcf(self, filter_dict, output):
        """ Read the VCF file and write the filter vcf file and return a data
        frame.

        """
        with open(output, "w") as fp:
            vcf_writer = vcf.Writer(fp, self)
            for variant in self:
                keep_line = self._filter_line(variant, filter_dict)
                if keep_line:
                    vcf_writer.write_record(variant)
        self._rewind()

    def _vcf_line_to_csv_line(self, vcf_line):
        alt_freq = self._compute_freq(vcf_line)
        strand_bal = self._compute_strand_bal(vcf_line)
        line_dict = {"chr": vcf_line.CHROM, "position": str(vcf_line.POS),
                "depth": vcf_line.INFO["DP"], "reference": vcf_line.REF,
                "alternative": "; ".join(str(x) for x in vcf_line.ALT), 
                "freebayes_score": vcf_line.QUAL, 
                "strand_balance": "; ".join("{0:.2f}".format(x) for x in \
                        strand_bal),
                "frequency": "; ".join("{0:.2f}".format(x) for x in alt_freq)} 
        try:
            annotation = vcf_line.INFO["EFF"][0].split("|")
            effect_type, effect_lvl = annotation[0].split("(")
            try:
                prot_effect, cds_effect = annotation[3].split("/")
            except ValueError:
                cds_effect = annotation[3]
                prot_effect = ""
            ann_dict = {"CDS_position": cds_effect[2:],
                        "annotation": effect_type,
                        "codon_change": annotation[2],
                        "gene_name": annotation[5],
                        "mutation_type": annotation[1],
                        "prot_effect": prot_effect[2:],
                        "prot_size": annotation[4],
                        "putative_impact": effect_lvl}
            line_dict = dict(line_dict, **ann_dict)
        except KeyError:
            pass
        return line_dict

    def _vcf_to_df(self):
        """
        """
        dict_list = [self._vcf_line_to_csv_line(variant) for variant in self]
        self.df = pd.DataFrame.from_records(dict_list)
        cols = self.df.columns.tolist()
        try:
            self.df = self.df[[cols[3], cols[10], cols[14], cols[1], cols[5], 
                    cols[7], cols[15], cols[6], cols[2], cols[9], cols[13],
                    cols[8], cols[0], cols[4], cols[11], cols[12]]]
        except (ValueError, IndexError):
            if cols:
                self.df = self.df[[cols[1], cols[5], cols[6], cols[0], cols[2],
                        cols[4], cols[7], cols[3]]]
        self._rewind()

    def _rewind(self):
        self._reader.seek(self.start_index)
        self.reader = (line.strip() for line in self._reader if line.strip())

    def to_csv(self, output_filename):
        self.df.to_csv(output_filename, index=False)
