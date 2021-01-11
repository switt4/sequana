# coding: utf-8
#
#  This file is part of Sequana software
#
#  Copyright (c) 2020 - Sequana Development Team
#
#  Distributed under the terms of the 3-clause BSD license.
#  The full license is in the LICENSE file, distributed with this software.
#
#  website: https://github.com/sequana/sequana
#  documentation: http://sequana.readthedocs.io
#
##############################################################################
"""Module to write variant calling report"""
import ast

import pandas as pd

from sequana.modules_report.base_module import SequanaBaseModule
from sequana.utils.datatables_js import DataTable


class RNAdiffModule(SequanaBaseModule):
    """ Write HTML report of variant calling. This class takes a csv file
    generated by sequana_variant_filter.
    """
    def __init__(self, data, output_filename="rnadiff.html",
        annotations="annotations.csv"):
        """.. rubric:: constructor

        """
        super().__init__()
        self.title = "RNAdiff"
        self.independent_module = True
        self.module_command = "--module rnadiff"

        from sequana.rnadiff import RNADiffResults
        self.rnadiff = RNADiffResults(data, annotations=annotations)

        self.df = data.df.copy()
        self.df.columns = [x.replace(".", "") for x in self.df.columns]


        # nice layout for the report
        import seaborn
        seaborn.set()
        self.create_report_content()

        self.create_html(output_filename)
        import matplotlib
        matplotlib.rc_file_defaults()


    def create_report_content(self):
        self.sections = list()

        self.summary()
        self.add_plot_count_per_sample()
        self.add_cluster()
        self.add_dge()
        self.add_volcano()
        self.add_rnadiff_table()

    def summary(self):
        """ Add information of filter.
        """
        S = self.rnadiff.summary()

        A = len(self.df.query("padj<=0.05 and log2FoldChange>1"))
        B = len(self.df.query("padj<=0.05 and log2FoldChange<-1"))


 
        # set options
        options = {
            'scrollX': 'true',
            'pageLength': 20,
            'scrollCollapse': 'true',
        'dom': '',
            'buttons': []}

        df = pd.DataFrame({
            'Description': ['Number of DGE (any FC)', 'Number of DGE (|FC| > 1)'],
            'Down': [S.loc['down'][0], B], 
            'Up': [S.loc['up'][0], A], 
            'Total': [S.loc['all'][0], A+B]})
        df = df[['Description', 'Down', 'Up', 'Total']] 
        datatable = DataTable(df, 'dge')
        datatable.datatable.datatable_options = options
        js_all = datatable.create_javascript_function()
        html = datatable.create_datatable(float_format='%d')

        self.sections.append({
            'name': "Summary",
            'anchor': 'filters_option',
            'content':
                """
<p>The final Differententially Gene Expression (DGE) analysis
led to {} up and {} down genes (total {}). Filtering out the log2 fold change
(FC) below 1 (or -1) gives {} up and {} down (total of {}). <br> {} {} </p>""".format(S.loc['up'][0],
S.loc['down'][0],
S.loc['all'][0], A, B, A+B, js_all , html)
        })

    def add_cluster(self):
        style = "width:65%"
        def dendogram(filename):
            import pylab
            pylab.ioff()
            pylab.clf()
            self.rnadiff.plot_dendogram()
            pylab.savefig(filename)
            pylab.close()
        html_dendogram = """<p>The following image shows a hierarchical
clustering of the whole sample set. An euclidean distance is computed between
samples. The dendogram itself is built using the <a
href="https://en.wikipedia.org/wiki/Ward%27s_method"> Ward method </a>. The data was log-transformed first.
</p>{}<hr>""".format(
        self.create_embedded_png(dendogram, "filename", style=style))

        def pca(filename):
            import pylab
            pylab.ioff()
            pylab.clf()
            variance = self.rnadiff.plot_pca(2)
            pylab.savefig(filename)
            pylab.close()
        html_pca = """<p>The expriment variability is also represented by a
principal component analysis as shown here below. The two main components are
represented. We expect the ﬁrst principal component (PC1) o
separate samples from the diﬀerent biological conditions, meaning that the biological variability is
the main source of variance in the data. Hereafter is also a 3D representation
of the PCA where the first 3 components are shwon.

</p>{}<hr>""".format(
            self.create_embedded_png(pca, "filename", style=style))

        from plotly import offline
        fig = self.rnadiff.plot_pca(n_components=3, plotly=True)
        html_pca_plotly = offline.plot(fig, output_type="div",include_plotlyjs=False)

        self.sections.append({
           "name": "Clusterisation",
           "anchor": "table",
           "content": html_dendogram + html_pca + html_pca_plotly
         })

    def add_plot_count_per_sample(self):
        style = "width:65%"
        import pylab
        def plotter(filename):
            pylab.ioff()
            pylab.clf()
            self.rnadiff.plot_count_per_sample()
            pylab.savefig(filename)
            pylab.close()
        html1 = """<p>The following image shows the total number of counted reads
for each sample. We expect counts to be similar within conditions. They may be
different across conditions. Note that variation may happen (e.g., different rRNA contamination
levels, library concentrations, etc).<p>{}<hr>""".format(
         self.create_embedded_png(plotter, "filename", style=style))

        

        def null_counts(filename):
            pylab.ioff()
            pylab.clf()
            self.rnadiff.plot_percentage_null_read_counts()
            pylab.savefig(filename)
            pylab.close()
        
        html_null = """<p>The next image shows the percentage of features with no
read count in each sample (taken individually). Features with null read counts
in <b>all</b> samples are not
taken into account in the analysis (black dashed line). Fold-change and p-values
will be set to NA in the final results</p> {}<hr>""".format(
            self.create_embedded_png(null_counts, "filename", style=style))

        def count_density(filename):
            pylab.ioff()
            pylab.clf()
            self.rnadiff.plot_density()
            pylab.savefig(filename)
            pylab.close()
        html_density = """<p>In the following figure, we show the distribution
of read counts for each sample (log10 scale). We expect replicates to behave in
a similar fashion. The mode depends on the biological conditions and organism
considered.</p> {}<hr>""".format(
            self.create_embedded_png(count_density, "filename", style=style))

        def best_count(filename):
            pylab.ioff()
            pylab.clf()
            self.rnadiff.plot_feature_most_present()
            pylab.savefig(filename)
            pylab.close()
        html_feature = """<p>In the following figure, we show for each sample the feature that
capture the highest proportion of the reads considered. This should not impact
the DESEq2 normalization. We expect consistence across samples within a single
conditions</p> {}<hr>""".format(
            self.create_embedded_png(best_count, "filename", style=style))


        self.sections.append({
           "name": "Diagnostic plots",
           "anchor": "table",
           "content": html1 +  html_null + html_density + html_feature
         })


    def add_dge(self):
        style = "width:45%"
        def rawcount(filename):
            import pylab
            pylab.ioff()
            pylab.clf()
            self.rnadiff.boxplot_rawdata()
            ax = pylab.gca()
            xticklabels = ax.get_xticklabels()
            ax.set_xticklabels(xticklabels, rotation=45, ha='right')
            try: pylab.tight_layout()
            except:pass
            pylab.savefig(filename)
            pylab.close()
        def normedcount(filename):
            import pylab
            pylab.ioff()
            pylab.clf()
            self.rnadiff.boxplot_normeddata()
            ax = pylab.gca()
            xticklabels = ax.get_xticklabels()
            ax.set_xticklabels(xticklabels, rotation=45, ha='right')
            try: pylab.tight_layout()
            except:pass
            pylab.savefig(filename)
            pylab.close()
        html_boxplot = """<p>A normalization of the data is performed to correct
the systematic technical biases due to different counts across samples. The 
normalization is performed with DESeq2. It relies on the hypothess that most
features are not differentially expressed. It computes a scaling factor for each
sample. Normalizes read counts are obtained by dividing raw read counts by the
scaling factor associated with the sample they belong to.

Boxplots are often used as a qualitative measure of the quality of the normalization process, asthey show how distributions are globally aﬀected during this process. We expect normalization to
stabilize distributions across samples.
In the left figure we show the raw counts while the right figure shows the
normalised counts. 
</p>"""
        img1 = self.create_embedded_png(rawcount, "filename", style=style)
        img2 = self.create_embedded_png(normedcount, "filename", style=style)


        self.sections.append({
           "name": "Normalisation",
           "anchor": "table",
           "content": html_boxplot + img1 + img2 + "</hr>" 
         })

        def plot_pvalue_hist(filename):
            import pylab; pylab.ioff(); pylab.clf()
            self.rnadiff.plot_pvalue_hist()
            pylab.savefig(filename); pylab.close()

        def plot_padj_hist(filename):
            import pylab; pylab.ioff(); pylab.clf()
            self.rnadiff.plot_padj_hist()
            pylab.savefig(filename); pylab.close()
        img1 = self.create_embedded_png(plot_pvalue_hist, "filename", style=style)
        img2 = self.create_embedded_png(plot_padj_hist, "filename", style=style)

        description = """<p>The differential analysis is based on DESeq2. This
tool aim at fitting one linear model per feature. Given the replicates in
condition one and the replicates in condition two, a p-value is computed to
indicate whether the feature (gene) is differentially expressed. Then, all
p-values are corrected for multiple testing. </p>

<p>It may happen that one sample seems unrelated to the rest. For every feature
and every model, Cook's distance is computed. It reflects how the sample matches
the model. A large value indicates an outlier count and p-values are not coputed
for that feature.</p>

<p>
In the dispersion estimation and model fitting is done, statistical testing is
performed. The distribution of raw p-values computed by the statistical test 
is expected to be a mixture of a uniform distribution on [0, 1] and a peak
around 0 corresponding to the diﬀerentially expressed features. This may not
always be the case. </p>"""

        self.sections.append({
           "name": "Diagnostic plots",
           "anchor": "table",
           "content": description + img1 + img2 
         })

    def add_volcano(self):

        style = "width:45%"

        def plot_volcano(filename):
            import pylab; pylab.ioff(); pylab.clf()
            self.rnadiff.plot_volcano()
            pylab.savefig(filename); pylab.close()
        html_volcano = """<p>The volcano plot here below shows the diﬀerentially
expressed features in red. A volcano plot represents the log10 of the adjusted P
value as a function of the log ratio of diﬀerential expression. </p>"""
        img3 = self.create_embedded_png(plot_volcano, "filename", style=style)

        fig = self.rnadiff.plot_volcano(plotly=True)
        from plotly import offline
        plotly = offline.plot(fig, output_type="div", include_plotlyjs=False)

        self.sections.append({
           "name": "DGE (volcano plots)",
           "anchor": "table",
           "content":  html_volcano + img3 + "<hr>" +"""<p>The following plot
contains the same information as above but with an interactive plot. Please
place the mouse cursor on the feature of interest.</p>""" +plotly
         })

    def add_rnadiff_table(self):
        """ RNADiff.        """
        from pylab import log10
        df = self.df.copy()
        log10padj = -log10(df['padj'])
        df.insert(df.columns.get_loc('padj')+1, 'log10_padj', log10padj)

        try:
            del df['dispGeneEst']
            del df['dispFit']
            del df['dispMap']
            del df['dispersion']
        except:pass


        # set options
        options = {'scrollX': 'true',
            'pageLength': 20,
            'scrollCollapse': 'true',
            'dom': 'Bfrtip',
            'buttons': ['copy', 'csv']}

        datatable = DataTable(df, 'rnadiff_all')
        datatable.datatable.datatable_options = options
        js_all = datatable.create_javascript_function()
        html_tab_all = datatable.create_datatable(float_format='%.3e')

        df_sign = df.query("padj<=0.05 and (log2FoldChange>0.5 or log2FoldChange<-0.5)")

        datatable = DataTable(df_sign, 'rnadiff_sign')
        datatable.datatable.datatable_options = options
        js_sign = datatable.create_javascript_function()
        html_tab_sign = datatable.create_datatable(float_format='%.3e')


        self.sections.append({
            'name': "Tables",
            'anchor': 'stats',
            'content':
                """<p>The following tables give all DGE results. The
first table contains all significant genes (adjusted p-value below 0.05 and
absolute fold change of at least 0.5). The following tables contains all results
without any filtering. Here is a short explanation for each column:
<ul>
<li> baseMean: base mean over all samples</li>
<li> norm.sampleName: rounded normalized counts per sample</li>
<li> FC: fold change in natural base</li>
<li> log2FoldChange: log2 Fold Change estimated by the model. Reflects change
between the condition versus the reference condition</li>
<li> stat: Wald statistic for the coefficient (contrast) tested</li>
<li> pvalue: raw p-value from statistical test</li>
<li> padj: adjusted pvalue. Used for cutoff at 0.05 </li>
<li> betaConv: convergence of the coefficients of the model </li>
<li> maxCooks: maximum Cook's distance of the feature </li>
<li> outlier: indicate if the feature is an outlier according to Cook's distance
</li>
</ul>
</p>
{} {} {} {}"""
                .format(js_sign, html_tab_sign, js_all, html_tab_all)
        })