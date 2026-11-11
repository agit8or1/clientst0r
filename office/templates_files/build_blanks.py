"""Regenerate blank.docx / blank.xlsx / blank.pptx in this directory.

    venv/bin/python office/templates_files/build_blanks.py

Run once; the outputs are committed and checked by office/tests.py
(BlankTemplateTests): valid ZIP, the right [Content_Types].xml main part,
every relationship target present, no macros. The workbook is written by
openpyxl (MIT); the Word and PowerPoint packages are the minimal part sets the
ECMA-376 specification requires, written out below by hand so no extra
dependency is needed. Not imported by the application.
"""
import io
import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIXED_DATE = (2026, 1, 1, 0, 0, 0)

CT = 'http://schemas.openxmlformats.org/package/2006/content-types'
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
R_OFFICE = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'

CORE = XML_DECL + (
    '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
    '<dc:title></dc:title><dc:creator>clientst0r</dc:creator>'
    '<dcterms:created xsi:type="dcterms:W3CDTF">2026-01-01T00:00:00Z</dcterms:created>'
    '<dcterms:modified xsi:type="dcterms:W3CDTF">2026-01-01T00:00:00Z</dcterms:modified>'
    '</cp:coreProperties>')

APP = XML_DECL + (
    '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
    '<Application>clientst0r</Application></Properties>')


def rels(entries):
    body = ''.join(f'<Relationship Id="{rid}" Type="{typ}" Target="{target}"/>'
                   for rid, typ, target in entries)
    return XML_DECL + f'<Relationships xmlns="{REL}">{body}</Relationships>'


def content_types(overrides):
    body = ('<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>')
    body += ''.join(f'<Override PartName="{p}" ContentType="{t}"/>' for p, t in overrides)
    return XML_DECL + f'<Types xmlns="{CT}">{body}</Types>'


def write_zip(path, parts):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for name, data in parts:
            info = zipfile.ZipInfo(name, FIXED_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)


PKG_RELS = lambda main: rels([  # noqa: E731
    ('rId1', f'{R_OFFICE}/officeDocument', main),
    ('rId2', 'http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties',
     'docProps/core.xml'),
    ('rId3', f'{R_OFFICE}/extended-properties', 'docProps/app.xml'),
])
PROPS_CT = [
    ('/docProps/core.xml', 'application/vnd.openxmlformats-package.core-properties+xml'),
    ('/docProps/app.xml', 'application/vnd.openxmlformats-officedocument.extended-properties+xml'),
]


def build_docx():
    w = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    document = XML_DECL + (
        f'<w:document xmlns:w="{w}" xmlns:r="{R_OFFICE}"><w:body><w:p/>'
        '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" '
        'w:header="720" w:footer="720" w:gutter="0"/></w:sectPr></w:body></w:document>')
    styles = XML_DECL + (
        f'<w:styles xmlns:w="{w}"><w:docDefaults><w:rPrDefault><w:rPr>'
        '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Calibri" w:cs="Calibri"/>'
        '<w:sz w:val="22"/><w:szCs w:val="22"/><w:lang w:val="en-US"/></w:rPr></w:rPrDefault>'
        '<w:pPrDefault><w:pPr><w:spacing w:after="160" w:line="259" w:lineRule="auto"/></w:pPr>'
        '</w:pPrDefault></w:docDefaults>'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/>'
        '<w:qFormat/></w:style></w:styles>')
    doc_rels = rels([('rId1', f'{R_OFFICE}/styles', 'styles.xml')])
    ct = content_types([
        ('/word/document.xml',
         'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'),
        ('/word/styles.xml', 'application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml'),
    ] + PROPS_CT)
    write_zip(os.path.join(HERE, 'blank.docx'), [
        ('[Content_Types].xml', ct), ('_rels/.rels', PKG_RELS('word/document.xml')),
        ('word/document.xml', document), ('word/styles.xml', styles),
        ('word/_rels/document.xml.rels', doc_rels),
        ('docProps/core.xml', CORE), ('docProps/app.xml', APP),
    ])


def build_xlsx():
    from openpyxl import Workbook
    wb = Workbook()
    wb.active.title = 'Sheet1'
    buf = io.BytesIO()
    wb.save(buf)
    with open(os.path.join(HERE, 'blank.xlsx'), 'wb') as fh:
        fh.write(buf.getvalue())


A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
P = 'http://schemas.openxmlformats.org/presentationml/2006/main'


def _theme():
    def solid(scheme):
        return f'<a:solidFill><a:schemeClr val="{scheme}"/></a:solidFill>'
    colors = (
        '<a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1>'
        '<a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>'
        '<a:dk2><a:srgbClr val="44546A"/></a:dk2><a:lt2><a:srgbClr val="E7E6E6"/></a:lt2>'
        '<a:accent1><a:srgbClr val="4472C4"/></a:accent1><a:accent2><a:srgbClr val="ED7D31"/></a:accent2>'
        '<a:accent3><a:srgbClr val="A5A5A5"/></a:accent3><a:accent4><a:srgbClr val="FFC000"/></a:accent4>'
        '<a:accent5><a:srgbClr val="5B9BD5"/></a:accent5><a:accent6><a:srgbClr val="70AD47"/></a:accent6>'
        '<a:hlink><a:srgbClr val="0563C1"/></a:hlink><a:folHlink><a:srgbClr val="954F72"/></a:folHlink>')
    fonts = ('<a:majorFont><a:latin typeface="Calibri Light"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont>'
             '<a:minorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont>')
    fill3 = solid('phClr') * 3
    lines = ''.join(f'<a:ln w="{w}" cap="flat" cmpd="sng" algn="ctr">{solid("phClr")}'
                    '<a:prstDash val="solid"/><a:miter lim="800000"/></a:ln>' for w in (6350, 12700, 19050))
    effects = '<a:effectStyle><a:effectLst/></a:effectStyle>' * 3
    fmt = (f'<a:fillStyleLst>{fill3}</a:fillStyleLst><a:lnStyleLst>{lines}</a:lnStyleLst>'
           f'<a:effectStyleLst>{effects}</a:effectStyleLst><a:bgFillStyleLst>{fill3}</a:bgFillStyleLst>')
    return XML_DECL + (
        f'<a:theme xmlns:a="{A}" name="Office Theme"><a:themeElements>'
        f'<a:clrScheme name="Office">{colors}</a:clrScheme>'
        f'<a:fontScheme name="Office">{fonts}</a:fontScheme>'
        f'<a:fmtScheme name="Office">{fmt}</a:fmtScheme>'
        '</a:themeElements><a:objectDefaults/><a:extraClrSchemeLst/></a:theme>')


def _sp_tree(extra=''):
    return ('<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
            '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
            '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
            f'{extra}</p:spTree>')


def _placeholder(id_, name, ph, x, y, cx, cy):
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{id_}" name="{name}"/><p:cNvSpPr><a:spLocks noGrp="1"/>'
            f'</p:cNvSpPr><p:nvPr>{ph}</p:nvPr></p:nvSpPr><p:spPr><a:xfrm><a:off x="{x}" y="{y}"/>'
            f'<a:ext cx="{cx}" cy="{cy}"/></a:xfrm></p:spPr><p:txBody><a:bodyPr/><a:lstStyle/>'
            '<a:p><a:endParaRPr lang="en-US"/></a:p></p:txBody></p:sp>')


CTR_TITLE = '<p:ph type="ctrTitle"/>'


def build_pptx():
    ns = f'xmlns:a="{A}" xmlns:r="{R_OFFICE}" xmlns:p="{P}"'
    clr_map = ('<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" '
               'accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" '
               'hlink="hlink" folHlink="folHlink"/>')
    title_ph = _placeholder(2, 'Title 1', '<p:ph type="title"/>', 838200, 365125, 10515600, 1325563)
    body_ph = _placeholder(3, 'Text Placeholder 2', '<p:ph type="body" idx="1"/>',
                           838200, 1825625, 10515600, 4351338)
    presentation = XML_DECL + (
        f'<p:presentation {ns} saveSubsetFonts="1">'
        '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
        '<p:sldIdLst><p:sldId id="256" r:id="rId2"/></p:sldIdLst>'
        '<p:sldSz cx="12192000" cy="6858000"/><p:notesSz cx="6858000" cy="9144000"/>'
        '<p:defaultTextStyle><a:defPPr><a:defRPr lang="en-US"/></a:defPPr></p:defaultTextStyle>'
        '</p:presentation>')
    master = XML_DECL + (
        f'<p:sldMaster {ns}><p:cSld><p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg>'
        f'{_sp_tree(title_ph + body_ph)}</p:cSld>{clr_map}'
        '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
        '<p:txStyles><p:titleStyle><a:lvl1pPr><a:defRPr sz="4400"/></a:lvl1pPr></p:titleStyle>'
        '<p:bodyStyle><a:lvl1pPr><a:defRPr sz="2800"/></a:lvl1pPr></p:bodyStyle>'
        '<p:otherStyle><a:defPPr><a:defRPr lang="en-US"/></a:defPPr></p:otherStyle></p:txStyles>'
        '</p:sldMaster>')
    layout = XML_DECL + (
        f'<p:sldLayout {ns} type="title" preserve="1"><p:cSld name="Title Slide">'
        f'{_sp_tree(_placeholder(2, "Title 1", CTR_TITLE, 1524000, 1122363, 9144000, 2387600))}'
        '</p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>')
    slide = XML_DECL + (
        f'<p:sld {ns}><p:cSld>'
        f'{_sp_tree(_placeholder(2, "Title 1", CTR_TITLE, 1524000, 1122363, 9144000, 2387600))}'
        '</p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>')
    pml = 'application/vnd.openxmlformats-officedocument.presentationml'
    ct = content_types([
        ('/ppt/presentation.xml', f'{pml}.presentation.main+xml'),
        ('/ppt/slideMasters/slideMaster1.xml', f'{pml}.slideMaster+xml'),
        ('/ppt/slideLayouts/slideLayout1.xml', f'{pml}.slideLayout+xml'),
        ('/ppt/slides/slide1.xml', f'{pml}.slide+xml'),
        ('/ppt/theme/theme1.xml', 'application/vnd.openxmlformats-officedocument.theme+xml'),
    ] + PROPS_CT)
    write_zip(os.path.join(HERE, 'blank.pptx'), [
        ('[Content_Types].xml', ct), ('_rels/.rels', PKG_RELS('ppt/presentation.xml')),
        ('ppt/presentation.xml', presentation),
        ('ppt/_rels/presentation.xml.rels', rels([
            ('rId1', f'{R_OFFICE}/slideMaster', 'slideMasters/slideMaster1.xml'),
            ('rId2', f'{R_OFFICE}/slide', 'slides/slide1.xml'),
            ('rId3', f'{R_OFFICE}/theme', 'theme/theme1.xml'),
        ])),
        ('ppt/slideMasters/slideMaster1.xml', master),
        ('ppt/slideMasters/_rels/slideMaster1.xml.rels', rels([
            ('rId1', f'{R_OFFICE}/slideLayout', '../slideLayouts/slideLayout1.xml'),
            ('rId2', f'{R_OFFICE}/theme', '../theme/theme1.xml'),
        ])),
        ('ppt/slideLayouts/slideLayout1.xml', layout),
        ('ppt/slideLayouts/_rels/slideLayout1.xml.rels', rels([
            ('rId1', f'{R_OFFICE}/slideMaster', '../slideMasters/slideMaster1.xml'),
        ])),
        ('ppt/slides/slide1.xml', slide),
        ('ppt/slides/_rels/slide1.xml.rels', rels([
            ('rId1', f'{R_OFFICE}/slideLayout', '../slideLayouts/slideLayout1.xml'),
        ])),
        ('ppt/theme/theme1.xml', _theme()),
        ('docProps/core.xml', CORE), ('docProps/app.xml', APP),
    ])


if __name__ == '__main__':
    build_docx()
    build_xlsx()
    build_pptx()
    print('wrote blank.docx, blank.xlsx, blank.pptx')
