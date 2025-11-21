const puppeteer = require('puppeteer');

async function extractLeadsRealtime(nicho, regiao, quantidade, onNewLead, onProgress) {
  let browser;

  try {
    onProgress({ status: 'Iniciando...', percent: 5 });

    browser = await puppeteer.launch({
      headless: 'new',
      args: ['--no-sandbox', '--disable-setuid-sandbox']
    });

    const page = await browser.newPage();
    const query = `${nicho} ${regiao}`;

    const uniqueEstabelecimentos = new Map();
    let currentPageNum = 0;
    const maxPages = 50;
    let paginasVaziasSeguidas = 0;

    while (uniqueEstabelecimentos.size < quantidade && currentPageNum < maxPages) {
      const start = currentPageNum * 10;
      const url = `https://www.google.com/search?tbm=lcl&hl=pt-BR&gl=BR&q=${encodeURIComponent(query)}&start=${start}`;

      console.log(`Acessando página ${currentPageNum + 1}: ${url}`);
      onProgress({
        status: `Buscando página ${currentPageNum + 1}...`,
        percent: 10 + Math.floor((currentPageNum / maxPages) * 20)
      });

      await page.goto(url, { waitUntil: 'networkidle0', timeout: 30000 });
      await new Promise(r => setTimeout(r, 2000));

      // Extrai estabelecimentos da página atual
      const estabelecimentosDaPagina = await page.evaluate(() => {
        const results = [];
        const seen = new Set();

        // Pega TODOS os divs com jscontroller
        const cards = document.querySelectorAll('div[jscontroller]');

        cards.forEach(card => {
          const text = card.textContent || '';

          // Busca nome
          const headings = card.querySelectorAll('div[role="heading"]');
          let nome = '';
          if (headings.length > 0) {
            nome = headings[0].textContent.trim();
          }

          // Se não tem nome, pula
          if (!nome || nome.length < 3 || nome.length > 150) return;

          // Filtra lixo
          if (/^(Ver mais|Pesquisar|Filtrar|Mapa|Lista|Anterior|Próxim|Direções|Salvar|Escolha)/i.test(nome)) {
            return;
          }

          // Busca telefone com TODAS as variações
          const phonePatterns = [
            /\(\d{2}\)\s?\d{4,5}[-\s]?\d{4}/g,
            /\d{2}\s?\d{4,5}[-\s]?\d{4}/g,
            /\+55\s?\(?\d{2}\)?\s?\d{4,5}[-\s]?\d{4}/g,
            /\(\d{2}\)\s?\d{8,9}/g,
            /\d{10,11}/g
          ];

          let telefone = null;
          for (const pattern of phonePatterns) {
            const matches = text.match(pattern);
            if (matches && matches.length > 0) {
              telefone = matches[0];
              break;
            }
          }

          // Só adiciona se tem telefone
          if (telefone) {
            const key = `${nome}|${telefone}`;
            if (!seen.has(key)) {
              seen.add(key);
              results.push({ nome, telefone });
            }
          }
        });

        return results;
      });

      console.log(`Página ${currentPageNum + 1}: ${estabelecimentosDaPagina.length} estabelecimentos com telefone`);

      if (estabelecimentosDaPagina.length === 0) {
        paginasVaziasSeguidas++;
        if (paginasVaziasSeguidas >= 5) {
          console.log('Encerrando busca - 5 páginas vazias seguidas');
          break;
        }
      } else {
        paginasVaziasSeguidas = 0;

        // Adiciona novos únicos
        let novosAdicionados = 0;
        estabelecimentosDaPagina.forEach(est => {
          const key = `${est.nome}|${est.telefone}`;
          if (!uniqueEstabelecimentos.has(key)) {
            uniqueEstabelecimentos.set(key, est);
            novosAdicionados++;
          }
        });

        console.log(`   → Novos únicos adicionados: ${novosAdicionados} de ${estabelecimentosDaPagina.length}`);
        console.log(`   → Total de únicos até agora: ${uniqueEstabelecimentos.size}`);
      }

      currentPageNum++;

      if (uniqueEstabelecimentos.size >= quantidade) {
        console.log(`✓ Quantidade de únicos atingida: ${uniqueEstabelecimentos.size} >= ${quantidade}`);
        break;
      }

      const percentComplete = Math.min(100, Math.floor((uniqueEstabelecimentos.size / quantidade) * 100));
      console.log(`Progresso: ${percentComplete}% (${uniqueEstabelecimentos.size}/${quantidade})`);
    }

    const unique = Array.from(uniqueEstabelecimentos.values());
    console.log(`Total coletado: ${unique.length} estabelecimentos únicos (${currentPageNum} páginas)`);

    if (unique.length === 0) {
      throw new Error('Nenhum resultado encontrado');
    }

    if (unique.length < quantidade) {
      onProgress({
        status: `Encontrados ${unique.length} contatos de ${quantidade} solicitados.`,
        percent: 35
      });
      console.log(`⚠️ Solicitado: ${quantidade}, Encontrado: ${unique.length}`);
      await new Promise(r => setTimeout(r, 2000));
    }

    onProgress({ status: 'Enviando contatos...', percent: 40 });

    const limit = Math.min(unique.length, quantidade);

    for (let i = 0; i < limit; i++) {
      const est = unique[i];

      onProgress({
        status: `Enviando ${i + 1}/${limit}...`,
        percent: 40 + Math.floor((i / limit) * 55)
      });

      onNewLead({
        nome: est.nome,
        telefone: est.telefone,
        endereco: 'Não disponível',
        index: i + 1
      });

      console.log(`✓ [${i + 1}] ${est.nome} - ${est.telefone}`);
      await new Promise(r => setTimeout(r, 30));
    }

    onProgress({ status: 'Concluído!', percent: 100 });
    console.log(`Total enviado: ${limit}`);

  } catch (error) {
    console.error('Erro:', error);
    throw new Error(`Erro: ${error.message}`);
  } finally {
    if (browser) await browser.close();
  }
}

module.exports = { extractLeadsRealtime };
