<?xml version="1.0" encoding="UTF-8"?>
<!--
  leizilla-to-lexml.xsl — converte Leizilla XML v0.1 para LexML brasileiro v1.0.

  Decisão estrutural (docs/SCHEMA.md §6):
  LexML é representação reduzida gerada sob demanda. Não é round-trip.
  Várias dimensões do Leizilla XML não têm equivalente LexML e são
  descartadas ou colapsadas:

  - Timeline <versao>: colapsamos para a versão vigente em <lei vigente-em="X">
    (a versão onde X ∈ [versao.em, próximo terminator)). Histórico mapeia para
    LexML <Alteracao> quando possível, mas a forma como LexML modela isso é
    muito diferente — versões anteriores são DESCARTADAS por padrão neste XSLT.
  - <fonte diverge="true"> + <texto> divergente: DESCARTADOS. LexML não modela
    divergência multi-fonte.
  - <inicio tipo>: DESCARTADO. LexML enactment/period attrs não mapeiam direto.
  - <revogacao>: parcial vira `situacao="revogado"` no Artigo; total vira
    `situacao="revogado"` no <Norma>. Tipo (expressa/tacita/inconstitucionalidade)
    é descartado.
  - <dispositivo path="ocr-ruim*">: DESCARTADO. LexML não tem fallback para
    OCR não-estruturado. Lei só-ocr-ruim vira <Articulacao> vazia (XSD-inválido)
    — política upstream (SCHEMA.md §4.7): leis assim não publicam parsed item.

  Limitações desta versão:
  - Apenas a versão vigente é exportada. Histórico, alterações e revogações
    parciais ficam como atributos `situacao` quando aplicável.
  - Não emite <Caput> próprio para artigos que só têm texto direto sem
    parágrafos: emite <Caput><p>{texto}</p></Caput> sempre (LexML ArticleType
    requer Caput obrigatório quando não há DispositivoGenerico).
  - Tradução de rótulos é heurística baseada em path. Ver `format-rotulo` template.
-->
<xsl:stylesheet version="1.0"
                xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
                xmlns:lz="https://leizilla.org/lei/0.1"
                xmlns="http://www.lexml.gov.br/1.0"
                exclude-result-prefixes="lz">

  <xsl:output method="xml" encoding="UTF-8" indent="yes"/>
  <xsl:strip-space elements="*"/>

  <!-- ==================================================================
       Root: <lei> → <LexML><Metadado/><Norma/></LexML>
       ================================================================== -->

  <xsl:template match="/lz:lei">
    <LexML>
      <Metadado>
        <Identificacao>
          <xsl:attribute name="URN">
            <xsl:choose>
              <xsl:when test="@urn-lex">
                <xsl:value-of select="@urn-lex"/>
              </xsl:when>
              <!-- Fallback URN quando lei não tem urn-lex (caso parsed fallback). -->
              <xsl:otherwise>
                <xsl:text>urn:lex:br;leizilla;fallback:0000-00-00;0</xsl:text>
              </xsl:otherwise>
            </xsl:choose>
          </xsl:attribute>
        </Identificacao>
      </Metadado>
      <Norma>
        <!-- Revogação total da lei: LexML não tem atributo 'situacao' no
             elemento <Norma>. A informação fica perdida no export. Para
             gov interop, lei totalmente revogada provavelmente não seria
             enviada via LexML (vai como documento separado). Documentado
             em SCHEMA.md §6.2. -->
        <xsl:call-template name="parte-inicial"/>
        <Articulacao>
          <xsl:apply-templates select="lz:dispositivo" mode="articulacao"/>
        </Articulacao>
      </Norma>
    </LexML>
  </xsl:template>

  <!-- ==================================================================
       <ParteInicial>: junta titulo-lei/ementa/preambulo (se presentes)
       ================================================================== -->

  <xsl:template name="parte-inicial">
    <xsl:variable name="titulo" select="lz:dispositivo[@path='titulo-lei']"/>
    <xsl:variable name="ementa" select="lz:dispositivo[@path='ementa']"/>
    <xsl:variable name="preambulo" select="lz:dispositivo[@path='preambulo']"/>
    <xsl:if test="$titulo or $ementa or $preambulo">
      <ParteInicial>
        <xsl:if test="$titulo">
          <Epigrafe id="epi1">
            <xsl:value-of select="$titulo/lz:versao[last()]/lz:texto"/>
          </Epigrafe>
        </xsl:if>
        <xsl:if test="$ementa">
          <Ementa id="ementa1">
            <xsl:value-of select="$ementa/lz:versao[last()]/lz:texto"/>
          </Ementa>
        </xsl:if>
        <xsl:if test="$preambulo">
          <Preambulo id="pre1">
            <p>
              <xsl:value-of select="$preambulo/lz:versao[last()]/lz:texto"/>
            </p>
          </Preambulo>
        </xsl:if>
      </ParteInicial>
    </xsl:if>
  </xsl:template>

  <!-- ==================================================================
       Articulacao: ignora titulo-lei/ementa/preambulo (já em ParteInicial),
       ignora ocr-ruim* (LexML não modela), emite o resto.
       ================================================================== -->

  <xsl:template match="lz:dispositivo" mode="articulacao">
    <xsl:choose>
      <xsl:when test="@path='titulo-lei' or @path='ementa' or @path='preambulo'"/>
      <xsl:when test="starts-with(@path, 'ocr-ruim')"/>
      <xsl:when test="starts-with(@path, 'art-')">
        <xsl:call-template name="emit-artigo"/>
      </xsl:when>
      <!-- Organizacionais: classificar pelo ÚLTIMO token do path
           (path organizacional é namespaceado: tit-2-cap-1-sec-3 →
           última especialização vence). Ordem mais específico → menos. -->
      <xsl:when test="contains(@path, '-subsec-') or starts-with(@path, 'subsec-')">
        <xsl:call-template name="emit-organizacional">
          <xsl:with-param name="elem-name">Subsecao</xsl:with-param>
        </xsl:call-template>
      </xsl:when>
      <xsl:when test="contains(@path, '-sec-') or starts-with(@path, 'sec-')">
        <xsl:call-template name="emit-organizacional">
          <xsl:with-param name="elem-name">Secao</xsl:with-param>
        </xsl:call-template>
      </xsl:when>
      <xsl:when test="contains(@path, '-cap-') or starts-with(@path, 'cap-')">
        <xsl:call-template name="emit-organizacional">
          <xsl:with-param name="elem-name">Capitulo</xsl:with-param>
        </xsl:call-template>
      </xsl:when>
      <xsl:when test="contains(@path, '-tit-') or starts-with(@path, 'tit-')">
        <xsl:call-template name="emit-organizacional">
          <xsl:with-param name="elem-name">Titulo</xsl:with-param>
        </xsl:call-template>
      </xsl:when>
      <xsl:when test="contains(@path, '-liv-') or starts-with(@path, 'liv-')">
        <xsl:call-template name="emit-organizacional">
          <xsl:with-param name="elem-name">Livro</xsl:with-param>
        </xsl:call-template>
      </xsl:when>
      <xsl:when test="contains(@path, '-parte-') or starts-with(@path, 'parte-')">
        <xsl:call-template name="emit-organizacional">
          <xsl:with-param name="elem-name">Parte</xsl:with-param>
        </xsl:call-template>
      </xsl:when>
      <xsl:when test="starts-with(@path, 'anexo-')">
        <!-- LexML modela anexos como ReferenciaAnexo em <Anexos>, não dentro
             de <Articulacao>. Suporte completo requer documento separado
             linkado. DESCARTADO neste XSLT — perda documentada. -->
      </xsl:when>
      <xsl:when test="starts-with(@path, 'disp-transitoria-')
                      or starts-with(@path, 'disp-final-')">
        <!-- Disposições transitórias/finais são artigos do ponto de vista
             jurídico, mas geralmente em <ParteFinal>. Aqui emitimos como
             Artigo regular dentro de Articulacao (perda: contexto temporal). -->
        <xsl:call-template name="emit-artigo"/>
      </xsl:when>
      <xsl:otherwise>
        <!-- Token não mapeado: skip silenciosamente. Consistency checker
             do Leizilla XML já garante que path é válido; aqui é guard
             contra evolução futura do token map. -->
      </xsl:otherwise>
    </xsl:choose>
  </xsl:template>

  <!-- ==================================================================
       Artigo
       ================================================================== -->

  <xsl:template name="emit-artigo">
    <Artigo>
      <xsl:attribute name="id">
        <xsl:call-template name="path-to-id"/>
      </xsl:attribute>
      <xsl:if test="lz:revogacao">
        <xsl:attribute name="situacao">revogado</xsl:attribute>
      </xsl:if>
      <Rotulo>
        <xsl:call-template name="rotulo-artigo"/>
      </Rotulo>
      <Caput>
        <xsl:attribute name="id">
          <xsl:call-template name="path-to-id"/>
          <xsl:text>_cpt</xsl:text>
        </xsl:attribute>
        <p>
          <xsl:value-of select="lz:versao[last()]/lz:texto"/>
        </p>
        <!-- Incisos diretos no caput (sem parágrafo) -->
        <xsl:apply-templates select="lz:dispositivo[starts-with(@path, concat(current()/@path, '-inc-'))]"
                             mode="inciso"/>
      </Caput>
      <!-- Parágrafos do artigo -->
      <xsl:apply-templates select="lz:dispositivo[contains(@path, '-par-')
                                                  and not(contains(substring-after(@path, '-par-'), '-'))]"
                           mode="paragrafo"/>
    </Artigo>
  </xsl:template>

  <!-- ==================================================================
       Parágrafo
       ================================================================== -->

  <xsl:template match="lz:dispositivo" mode="paragrafo">
    <Paragrafo>
      <xsl:attribute name="id">
        <xsl:call-template name="path-to-id"/>
      </xsl:attribute>
      <xsl:if test="lz:revogacao">
        <xsl:attribute name="situacao">revogado</xsl:attribute>
      </xsl:if>
      <Rotulo>
        <xsl:call-template name="rotulo-paragrafo"/>
      </Rotulo>
      <p>
        <xsl:value-of select="lz:versao[last()]/lz:texto"/>
      </p>
      <xsl:apply-templates select="lz:dispositivo[contains(@path, '-inc-')]"
                           mode="inciso"/>
    </Paragrafo>
  </xsl:template>

  <!-- ==================================================================
       Inciso / Alinea / Item
       ================================================================== -->

  <xsl:template match="lz:dispositivo" mode="inciso">
    <Inciso>
      <xsl:attribute name="id">
        <xsl:call-template name="path-to-id"/>
      </xsl:attribute>
      <Rotulo>
        <xsl:call-template name="rotulo-inciso"/>
      </Rotulo>
      <p><xsl:value-of select="lz:versao[last()]/lz:texto"/></p>
      <xsl:apply-templates select="lz:dispositivo[contains(@path, '-ali-')]"
                           mode="alinea"/>
    </Inciso>
  </xsl:template>

  <xsl:template match="lz:dispositivo" mode="alinea">
    <Alinea>
      <xsl:attribute name="id">
        <xsl:call-template name="path-to-id"/>
      </xsl:attribute>
      <Rotulo>
        <xsl:value-of select="substring-after(@path, 'ali-')"/>
        <xsl:text>)</xsl:text>
      </Rotulo>
      <p><xsl:value-of select="lz:versao[last()]/lz:texto"/></p>
      <xsl:apply-templates select="lz:dispositivo[contains(@path, '-item-')]"
                           mode="item"/>
    </Alinea>
  </xsl:template>

  <xsl:template match="lz:dispositivo" mode="item">
    <Item>
      <xsl:attribute name="id">
        <xsl:call-template name="path-to-id"/>
      </xsl:attribute>
      <Rotulo>
        <xsl:value-of select="substring-after(@path, 'item-')"/>
      </Rotulo>
      <p><xsl:value-of select="lz:versao[last()]/lz:texto"/></p>
    </Item>
  </xsl:template>

  <!-- ==================================================================
       Organizacionais (Livro / Titulo / Capitulo / Secao / Subsecao / Parte)
       ================================================================== -->

  <xsl:template name="emit-organizacional">
    <xsl:param name="elem-name"/>
    <xsl:element name="{$elem-name}" namespace="http://www.lexml.gov.br/1.0">
      <xsl:attribute name="id">
        <xsl:call-template name="path-to-id-organizacional"/>
      </xsl:attribute>
      <Rotulo>
        <xsl:value-of select="lz:versao[last()]/lz:texto"/>
      </Rotulo>
      <xsl:apply-templates select="lz:dispositivo" mode="articulacao"/>
    </xsl:element>
  </xsl:template>

  <!-- ==================================================================
       Helpers: rotulos derivados de path
       ================================================================== -->

  <xsl:template name="rotulo-artigo">
    <!-- art-N → "Art. Nº" (ordinal 1º-9º; Nº a partir de 10).
         LexML rotulo é livre, então emitimos "Art. N" simples. -->
    <xsl:text>Art. </xsl:text>
    <xsl:value-of select="substring-after(@path, 'art-')"/>
  </xsl:template>

  <xsl:template name="rotulo-paragrafo">
    <xsl:variable name="last-par" select="substring-after(@path, '-par-')"/>
    <xsl:choose>
      <xsl:when test="$last-par='unico'">
        <xsl:text>Parágrafo único</xsl:text>
      </xsl:when>
      <xsl:otherwise>
        <xsl:text>§ </xsl:text>
        <xsl:value-of select="$last-par"/>
      </xsl:otherwise>
    </xsl:choose>
  </xsl:template>

  <xsl:template name="rotulo-inciso">
    <!-- Simples: emite o número arábico. Idealmente seria romano, mas
         XSLT 1.0 não tem function de número→roman builtin. Refinamento. -->
    <xsl:value-of select="substring-after(@path, '-inc-')"/>
  </xsl:template>

  <!-- ==================================================================
       Helper: path → id LexML (substitui hífens entre tokens por _).
       art-5-par-2-inc-3-ali-a → art5_par2_inc3_ali3
       Mas LexML id pattern não permite letras em ali — precisa converter
       a→1, b→2 etc. Simplificação: aceitamos perda aqui (refinamento).
       ================================================================== -->

  <xsl:template name="path-to-id">
    <!--
      Leizilla path → LexML idArtigo.

      Casos:
        art-N           → artN
        art-N-X         → artN-X (renumeração letras; pattern aceita)
        art-N-par-M     → artN_parM
        art-N-par-unico → artN_par1u
        art-N-inc-K     → artN_cpt_incK  (insere _cpt implícito!)
        art-N-par-M-inc-K → artN_parM_incK
        art-N-..-inc-K-ali-X → ..._incK_aliP(X)  (X=letra → P=posição: a→1, b→2)
        art-N-..-ali-X-item-L → ..._aliP_iteL

      LexML pattern: art{N}(_cpt|_par{M})_inc{K}_ali{P}_ite{L}
    -->
    <xsl:variable name="path" select="@path"/>

    <!-- art-N or art-N-X -->
    <xsl:variable name="art-num">
      <xsl:choose>
        <xsl:when test="contains(substring-after($path, 'art-'), '-')">
          <xsl:value-of select="substring-before(substring-after($path, 'art-'), '-')"/>
        </xsl:when>
        <xsl:otherwise>
          <xsl:value-of select="substring-after($path, 'art-')"/>
        </xsl:otherwise>
      </xsl:choose>
    </xsl:variable>
    <xsl:text>art</xsl:text>
    <xsl:value-of select="$art-num"/>

    <!-- Componentes opcionais -->
    <xsl:variable name="after-art" select="substring-after($path, concat('art-', $art-num, '-'))"/>
    <xsl:if test="$after-art != ''">
      <xsl:call-template name="emit-id-componentes">
        <xsl:with-param name="tail" select="$after-art"/>
        <xsl:with-param name="has-par">false</xsl:with-param>
      </xsl:call-template>
    </xsl:if>
  </xsl:template>

  <xsl:template name="emit-id-componentes">
    <!-- Processa cauda do path: par-M, inc-K, ali-X, item-L sequenciais. -->
    <xsl:param name="tail"/>
    <xsl:param name="has-par"/>
    <xsl:choose>
      <xsl:when test="starts-with($tail, 'par-')">
        <xsl:variable name="par-val">
          <xsl:choose>
            <xsl:when test="contains(substring-after($tail, 'par-'), '-')">
              <xsl:value-of select="substring-before(substring-after($tail, 'par-'), '-')"/>
            </xsl:when>
            <xsl:otherwise>
              <xsl:value-of select="substring-after($tail, 'par-')"/>
            </xsl:otherwise>
          </xsl:choose>
        </xsl:variable>
        <xsl:text>_par</xsl:text>
        <xsl:choose>
          <xsl:when test="$par-val='unico'">1u</xsl:when>
          <xsl:otherwise><xsl:value-of select="$par-val"/></xsl:otherwise>
        </xsl:choose>
        <xsl:variable name="rest" select="substring-after($tail, concat('par-', $par-val))"/>
        <xsl:if test="$rest != ''">
          <xsl:call-template name="emit-id-componentes">
            <xsl:with-param name="tail" select="substring($rest, 2)"/>
            <xsl:with-param name="has-par">true</xsl:with-param>
          </xsl:call-template>
        </xsl:if>
      </xsl:when>
      <xsl:when test="starts-with($tail, 'inc-')">
        <!-- Inciso direto em artigo (sem par) → precisa _cpt antes. -->
        <xsl:if test="$has-par = 'false'">
          <xsl:text>_cpt</xsl:text>
        </xsl:if>
        <xsl:variable name="inc-num">
          <xsl:choose>
            <xsl:when test="contains(substring-after($tail, 'inc-'), '-')">
              <xsl:value-of select="substring-before(substring-after($tail, 'inc-'), '-')"/>
            </xsl:when>
            <xsl:otherwise>
              <xsl:value-of select="substring-after($tail, 'inc-')"/>
            </xsl:otherwise>
          </xsl:choose>
        </xsl:variable>
        <xsl:text>_inc</xsl:text>
        <xsl:value-of select="$inc-num"/>
        <xsl:variable name="rest" select="substring-after($tail, concat('inc-', $inc-num))"/>
        <xsl:if test="$rest != ''">
          <xsl:call-template name="emit-id-componentes">
            <xsl:with-param name="tail" select="substring($rest, 2)"/>
            <xsl:with-param name="has-par">true</xsl:with-param>
          </xsl:call-template>
        </xsl:if>
      </xsl:when>
      <xsl:when test="starts-with($tail, 'ali-')">
        <xsl:variable name="letter" select="substring($tail, 5, 1)"/>
        <xsl:variable name="pos">
          <xsl:call-template name="letter-to-pos">
            <xsl:with-param name="letter" select="$letter"/>
          </xsl:call-template>
        </xsl:variable>
        <xsl:text>_ali</xsl:text>
        <xsl:value-of select="$pos"/>
        <xsl:variable name="rest" select="substring($tail, 6)"/>
        <xsl:if test="$rest != ''">
          <xsl:call-template name="emit-id-componentes">
            <xsl:with-param name="tail" select="substring($rest, 2)"/>
            <xsl:with-param name="has-par">true</xsl:with-param>
          </xsl:call-template>
        </xsl:if>
      </xsl:when>
      <xsl:when test="starts-with($tail, 'item-')">
        <xsl:variable name="item-num">
          <xsl:choose>
            <xsl:when test="contains(substring-after($tail, 'item-'), '-')">
              <xsl:value-of select="substring-before(substring-after($tail, 'item-'), '-')"/>
            </xsl:when>
            <xsl:otherwise>
              <xsl:value-of select="substring-after($tail, 'item-')"/>
            </xsl:otherwise>
          </xsl:choose>
        </xsl:variable>
        <xsl:text>_ite</xsl:text>
        <xsl:value-of select="$item-num"/>
      </xsl:when>
    </xsl:choose>
  </xsl:template>

  <xsl:template name="letter-to-pos">
    <xsl:param name="letter"/>
    <xsl:value-of select="string-length(substring-before('abcdefghijklmnopqrstuvwxyz', $letter)) + 1"/>
  </xsl:template>

  <xsl:template name="path-to-id-organizacional">
    <!--
      Leizilla org path → LexML idAgregador.

      Casos:
        liv-N → livN
        tit-N → titN
        tit-N-cap-M → titN_capM
        tit-N-cap-M-sec-K → titN_capM_secK
        ...-subsec-X → ..._subX  (LexML usa "sub", não "subsec")
    -->
    <xsl:call-template name="org-path-emit">
      <xsl:with-param name="rest" select="@path"/>
      <xsl:with-param name="first">true</xsl:with-param>
    </xsl:call-template>
  </xsl:template>

  <xsl:template name="org-path-emit">
    <xsl:param name="rest"/>
    <xsl:param name="first"/>
    <!-- Identifica próximo token (liv/tit/cap/sec/subsec/parte) -->
    <xsl:variable name="tok">
      <xsl:choose>
        <xsl:when test="starts-with($rest, 'liv-')">liv</xsl:when>
        <xsl:when test="starts-with($rest, 'tit-')">tit</xsl:when>
        <xsl:when test="starts-with($rest, 'cap-')">cap</xsl:when>
        <xsl:when test="starts-with($rest, 'sec-')">sec</xsl:when>
        <xsl:when test="starts-with($rest, 'subsec-')">sub</xsl:when>
        <xsl:when test="starts-with($rest, 'parte-')">prt</xsl:when>
      </xsl:choose>
    </xsl:variable>
    <xsl:variable name="prefix-len">
      <xsl:choose>
        <xsl:when test="$tok='sub'">7</xsl:when>
        <xsl:when test="$tok='prt'">6</xsl:when>
        <xsl:otherwise>4</xsl:otherwise>
      </xsl:choose>
    </xsl:variable>
    <xsl:variable name="after" select="substring($rest, $prefix-len + 1)"/>
    <xsl:variable name="num">
      <xsl:choose>
        <xsl:when test="contains($after, '-')">
          <xsl:value-of select="substring-before($after, '-')"/>
        </xsl:when>
        <xsl:otherwise>
          <xsl:value-of select="$after"/>
        </xsl:otherwise>
      </xsl:choose>
    </xsl:variable>
    <xsl:if test="$first != 'true'">
      <xsl:text>_</xsl:text>
    </xsl:if>
    <xsl:value-of select="$tok"/>
    <xsl:value-of select="$num"/>
    <xsl:variable name="next" select="substring($after, string-length($num) + 2)"/>
    <xsl:if test="$next != ''">
      <xsl:call-template name="org-path-emit">
        <xsl:with-param name="rest" select="$next"/>
        <xsl:with-param name="first">false</xsl:with-param>
      </xsl:call-template>
    </xsl:if>
  </xsl:template>

</xsl:stylesheet>
