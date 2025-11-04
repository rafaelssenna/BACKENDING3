# Instruções para melhorar o Scraper
"""
Este arquivo contém todas as modificações necessárias para resolver o problema
dos nomes repetidos e melhorar o sistema de extração de leads.

Para aplicar as melhorias:
1. Substitua a função _extract_phones_from_page no arquivo scraper.py
2. Adicione a função _extract_business_details antes da função _primary_business_name
3. Substitua a função _primary_business_name para usar a nova função _extract_business_details
4. Adicione os novos seletores CSS às listas existentes
"""

# ------------------ NOVOS SELETORES A ADICIONAR ------------------

# Adicionar à lista RESULT_CONTAINERS:
RESULT_CONTAINERS_NEW = [
    ".uMdZh",  # 2024 local results
    ".Nv2PK",  # business card wrapper
    ".VkpGBb .cXedhc",  # nested result container
    "[data-attrid='kc:/location/location:address']",  # address containers often near phones
    ".I9GLp",  # new Maps integration
]

# Adicionar à lista LISTING_LINK_SELECTORS:
LISTING_LINK_SELECTORS_NEW = [
    "a[href*='maps/place'][data-cid]",  # Maps with CID
    "a[data-fid]",  # Feature ID links
    "a[jsname][href*='place']",  # JS-powered links
]

# Adicionar à lista NAME_CANDIDATES:
NAME_CANDIDATES_NEW = [
    "[data-attrid='title']",  # structured data title
    ".tAiQdd",  # 2024 business name
    "[aria-label*='Nome']",  # aria-label with name
    "[jsname] .fontHeadlineLarge",  # large headline in new layout
]

# ------------------ NOVA FUNÇÃO PARA EXTRAÇÃO DE DETALHES ------------------

async def _extract_business_details(page) -> Dict[str, Optional[str]]:
    """
    Extract comprehensive business details from a listing page.
    Returns a dict with name, address, category, etc.
    """
    if not _page_alive(page):
        return {"name": None, "address": None, "category": None}
    
    details = {
        "name": None,
        "address": None,
        "category": None,
        "additional": None
    }
    
    try:
        # Extract name using multiple methods
        # 1. meta[itemprop='name'] - most reliable when present
        meta = await page.locator("meta[itemprop='name']").count()
        if meta > 0:
            content = await page.locator("meta[itemprop='name']").first.get_attribute("content")
            if content and content.strip():
                details["name"] = content.strip()
        
        # 2. Try primary name selectors
        if not details["name"]:
            for sel in [s for s in PRIMARY_NAME_SELECTORS if "::attr" not in s and "meta" not in s]:
                loc = page.locator(sel)
                if await loc.count() > 0:
                    text = await loc.first.text_content()
                    if text and text.strip():
                        details["name"] = text.strip()
                        break
        
        # 3. Last resort: title
        if not details["name"]:
            title_loc = page.locator("title")
            if await title_loc.count() > 0:
                t = (await title_loc.first.text_content()) or ""
                t = t.replace(" - Google Maps", "").replace(" – Google Maps", "")
                t = t.replace(" - Pesquisa Google", "").replace(" – Pesquisa Google", "")
                t = t.strip()
                if t:
                    details["name"] = t
        
        # Extract address - helps differentiate similar businesses
        address_selectors = [
            "[data-item-id='address']",
            "[data-attrid='kc:/location/location:address']",
            ".rogA2c",
            ".LrzXr",
            "[aria-label*='Endereço']",
            "[aria-label*='Address']"
        ]
        
        for sel in address_selectors:
            loc = page.locator(sel)
            if await loc.count() > 0:
                text = await loc.first.text_content()
                if text and text.strip():
                    details["address"] = text.strip()
                    break
        
        # Extract category/type
        category_selectors = [
            "[jsaction*='pane.rating.category']",
            ".YhemCb",
            "[data-attrid='kc:/local:one line summary']",
            ".dbg0pd + div",
            "[aria-label*='Categoria']"
        ]
        
        for sel in category_selectors:
            loc = page.locator(sel)
            if await loc.count() > 0:
                text = await loc.first.text_content()
                if text and text.strip():
                    details["category"] = text.strip()
                    break
                    
        # Try additional descriptive text as fallback
        if not details["category"]:
            desc_selectors = [
                ".PYvSYb",
                ".IEKGEb",
                ".lqhpac"
            ]
            for sel in desc_selectors:
                loc = page.locator(sel)
                if await loc.count() > 0:
                    text = await loc.first.text_content()
                    if text and text.strip():
                        details["additional"] = text.strip()
                        break
                        
    except Exception as e:
        log.debug(f"Error extracting business details: {e}")
    
    return details

# ------------------ SUBSTITUIÇÃO DA FUNÇÃO _primary_business_name ------------------

async def _primary_business_name(page) -> Optional[str]:
    """
    Return the main business name when on the listing detail page (Google Maps card).
    Prioritises the exact card title and safe fallbacks.
    """
    details = await _extract_business_details(page)
    return details.get("name")

# ------------------ SUBSTITUIÇÃO DA FUNÇÃO _extract_phones_from_page ------------------

async def _extract_phones_from_page(page, default_name: Optional[str] = None) -> List[Dict[str, Optional[str]]]:
    """
    Extract phone numbers and corresponding business names from the current page.
    Enhanced version that includes business details to differentiate similar businesses.
    """
    leads: Dict[str, Dict[str, Optional[str]]] = {}
    if not _page_alive(page):
        return []

    try:
        # Determine whether we are on a listing (business details) page
        primary_details = {"name": default_name}
        try:
            url: str = page.url or ""
            if "/maps/place" in url or "/local/place" in url:
                primary_details = await _extract_business_details(page)
        except Exception:
            pass
        
        primary_name = primary_details.get("name")
        primary_address = primary_details.get("address")
        primary_category = primary_details.get("category") or primary_details.get("additional")

        # Passo 1: anchors tel:
        try:
            anchors = await page.query_selector_all("a[href^='tel:']")
        except Exception:
            anchors = []
        
        for a in anchors or []:
            try:
                href = (await a.get_attribute("href")) or ""
                text = (await a.inner_text()) or (await a.text_content()) or ""
                phone = normalize_br(href.replace("tel:", "")) or normalize_br(text)
                if not phone:
                    continue
                
                # Usar o nome já encontrado ou tentar encontrar um próximo
                name = primary_name or await _closest_name_for(page, a)
                
                # Adicionar detalhes para diferenciar negócios similares
                result = {
                    "phone": phone, 
                    "name": (name or None)
                }
                
                # Adicionar informações extras quando disponíveis para diferenciar estabelecimentos com mesmo nome
                if primary_address:
                    result["address"] = primary_address
                if primary_category:
                    result["category"] = primary_category
                    
                # Criar um identificador único para o nome se houver endereço
                if result.get("name") and result.get("address"):
                    # Extrair apenas o bairro/rua do endereço para um sufixo mais limpo
                    address_suffix = None
                    addr = result["address"]
                    
                    # Tentar extrair apenas informação relevante do endereço
                    if "," in addr:
                        parts = addr.split(",")
                        if len(parts) >= 2:
                            address_suffix = parts[0].strip()
                    
                    # Se não conseguiu extrair, use os primeiros 20 caracteres
                    if not address_suffix and len(addr) > 5:
                        address_suffix = addr[:20].strip()
                        
                    if address_suffix:
                        result["name_with_location"] = f"{result['name']} ({address_suffix})"
                    
                if phone not in leads:
                    leads[phone] = result
            except Exception:
                continue

        # Passo 2: blocos de resultados
        for sel in RESULT_CONTAINERS:
            if not _page_alive(page):
                break
            try:
                blocks = await page.query_selector_all(sel)
            except Exception:
                blocks = []
            for block in blocks or []:
                try:
                    txt = (await block.inner_text()) or ""
                except Exception:
                    txt = ""
                if not txt:
                    continue

                extracted = extract_phones_from_text(txt)
                if not extracted:
                    continue

                try:
                    # Tenta obter o nome e endereço do bloco
                    block_details = {
                        "name": None,
                        "address": None,
                        "category": None
                    }
                    
                    # Busca nome no bloco
                    name_in_block = await page.evaluate(
                        f"""(el) => {{
                            const sels = {NAME_CANDIDATES!r};
                            for (const s of sels) {{
                               const c = el.querySelector(s);
                               if (c && c.textContent) {{
                                   const t = c.textContent.trim();
                                   if (t) return t;
                               }}
                            }}
                            const a = el.querySelector('a[href*="/maps/place"],a[href*="/local/place"]');
                            if (a) {{
                                const al = (a.getAttribute('aria-label') || a.textContent || '').trim();
                                if (al) return al;
                            }}
                            return null;
                        }}""",
                        block,
                    )
                    block_details["name"] = name_in_block
                    
                    # Busca endereço no bloco
                    address_in_block = await page.evaluate(
                        """(el) => {
                            const addressSelectors = [
                                "[data-item-id='address']",
                                "[data-attrid='kc:/location/location:address']",
                                ".rogA2c",
                                ".LrzXr",
                                "[aria-label*='Endereço']",
                                ".rllt__details div:nth-child(2)"
                            ];
                            
                            for (const s of addressSelectors) {
                               const c = el.querySelector(s);
                               if (c && c.textContent) {
                                   const t = c.textContent.trim();
                                   if (t) return t;
                               }
                            }
                            return null;
                        }""",
                        block,
                    )
                    block_details["address"] = address_in_block
                    
                    # Busca categoria no bloco
                    category_in_block = await page.evaluate(
                        """(el) => {
                            const categorySelectors = [
                                "[jsaction*='pane.rating.category']",
                                ".YhemCb",
                                "[data-attrid='kc:/local:one line summary']",
                                ".dbg0pd + div",
                                ".rllt__details div:nth-child(3)"
                            ];
                            
                            for (const s of categorySelectors) {
                               const c = el.querySelector(s);
                               if (c && c.textContent) {
                                   const t = c.textContent.trim();
                                   if (t) return t;
                               }
                            }
                            return null;
                        }""",
                        block,
                    )
                    block_details["category"] = category_in_block
                    
                    # Usar nome do bloco ou fallback para o nome primário
                    final_name = block_details["name"]
                    if not final_name and primary_name:
                        final_name = primary_name
                        
                    # Usar endereço do bloco ou primário
                    final_address = block_details["address"] or primary_address
                    final_category = block_details["category"] or primary_category

                    for ph in extracted:
                        if ph not in leads:
                            result = {
                                "phone": ph,
                                "name": final_name
                            }
                            
                            if final_address:
                                result["address"] = final_address
                            if final_category:
                                result["category"] = final_category
                                
                            # Criar nome com localização para diferenciar estabelecimentos similares
                            if result.get("name") and result.get("address"):
                                addr = result["address"]
                                address_suffix = None
                                
                                if "," in addr:
                                    parts = addr.split(",")
                                    if len(parts) >= 2:
                                        address_suffix = parts[0].strip()
                                        
                                if not address_suffix and len(addr) > 5:
                                    address_suffix = addr[:20].strip()
                                    
                                if address_suffix:
                                    result["name_with_location"] = f"{result['name']} ({address_suffix})"
                                    
                            leads[ph] = result
                except Exception:
                    # Se falhar na extração avançada, continuar com o método simples
                    name_in_block = block_details.get("name") or primary_name

                    for ph in extracted:
                        if ph not in leads:
                            leads[ph] = {"phone": ph, "name": name_in_block}

        # Passo 3: fallback no corpo
        if not leads and _page_alive(page):
            try:
                body_text = await page.evaluate(
                    "() => document.body ? (document.body.innerText || '') : ''"
                )
            except Exception:
                body_text = ""
            for ph in extract_phones_from_text(body_text or ""):
                if ph not in leads:
                    leads[ph] = {"phone": ph, "name": primary_name}

    except Exception as e:
        log.error(f"Error extracting phones from page: {e}")
        pass

    # Processar os resultados para garantir que cada lead tenha nome único quando possível
    results = list(leads.values())
    
    # Resolver nomes duplicados - usar name_with_location quando disponível
    for result in results:
        if result.get("name_with_location"):
            result["name"] = result["name_with_location"]
            
        # Limpar campos internos que não queremos exportar
        if "name_with_location" in result:
            del result["name_with_location"]
            
    return results

# ------------------ INSTRUÇÕES DE APLICAÇÃO ------------------

"""
Para aplicar essas modificações:

1. Adicione os novos seletores às listas existentes:
   - Adicione RESULT_CONTAINERS_NEW à lista RESULT_CONTAINERS
   - Adicione LISTING_LINK_SELECTORS_NEW à lista LISTING_LINK_SELECTORS
   - Adicione NAME_CANDIDATES_NEW à lista NAME_CANDIDATES

2. Adicione a função _extract_business_details antes da função _primary_business_name

3. Substitua a função _primary_business_name pela versão fornecida

4. Substitua a função _extract_phones_from_page pela versão fornecida

Importante:
- Essas modificações garantirão que nomes duplicados sejam diferenciados usando informações de endereço
- Os leads agora retornarão com formato mais rico: {"phone": "...", "name": "...", "address": "...", "category": "..."}
- O arquivo main.py continuará funcionando normalmente já que ele espera apenas os campos "phone" e "name"
"""
