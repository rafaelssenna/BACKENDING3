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
                    if not block_details["name"] and primary_name:
                        name_in_block = primary_name
                    else:
                        name_in_block = None

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
            
    return results
