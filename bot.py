import os
from datetime import datetime, timedelta
from app import app
from models import db, Manicure, Servico, Cliente, Agendamento, Pacote, ClientePacote, ConfigHorario

# Dicionário em memória para guardar o "passo" de cada cliente
sessoes_ativas = {}

def obter_mensagem_menu(manicure_id):
    """Consulta o banco e monta o menu de serviços dinamicamente."""
    with app.app_context():
        servicos = Servico.query.filter_by(manicure_id=manicure_id).all()
        
        msg = "Olá! Sou a assistente virtual da agenda. 💅\n\n"
        msg += "Responda com o *NÚMERO* do serviço desejado:\n\n"
        
        for index, servico in enumerate(servicos, start=1):
            msg += f"*{index}.* {servico.nome_servico} - R$ {servico.valor:.2f}\n"
            
        msg += "\n*0.* Falar com atendente humana"
        
        mapa_servicos = {str(i): s.id for i, s in enumerate(servicos, start=1)}
        return msg, mapa_servicos

def calcular_horarios_livres(manicure_id, data_foco, servico_id):
    """Gera uma lista de horários disponíveis cruzando o expediente e a agenda atual."""
    dia_semana = data_foco.weekday() # Pega o número do dia (0 a 6)
    
    with app.app_context():
        # 1. Busca a configuração de expediente para o dia da semana
        config = ConfigHorario.query.filter_by(manicure_id=manicure_id, dia_semana=dia_semana, ativo=True).first()
        if not config:
            return [] # Não atende neste dia
            
        servico = Servico.query.get(servico_id)
        duracao_servico = timedelta(minutes=servico.duracao_minutos)
        
        # 2. Busca todos os agendamentos confirmados do dia para evitar conflitos
        inicio_dia = data_foco.replace(hour=0, minute=0, second=0)
        fim_dia = data_foco.replace(hour=23, minute=59, second=59)
        agendamentos_dia = Agendamento.query.filter(
            Agendamento.manicure_id == manicure_id,
            Agendamento.data_hora >= inicio_dia,
            Agendamento.data_hora <= fim_dia,
            Agendamento.status == "Confirmado"
        ).all()
        
        # 3. Converte os horários de string para objetos datetime manipuláveis
        fmt = "%H:%M"
        atual = data_foco.replace(hour=int(config.hora_inicio.split(':')[0]), minute=int(config.hora_inicio.split(':')[1]))
        limite = data_foco.replace(hour=int(config.hora_fim.split(':')[0]), minute=int(config.hora_fim.split(':')[1]))
        
        alm_ini = data_foco.replace(hour=int(config.almoco_inicio.split(':')[0]), minute=int(config.almoco_inicio.split(':')[1])) if config.almoco_inicio else None
        alm_fim = data_foco.replace(hour=int(config.almoco_fim.split(':')[0]), minute=int(config.almoco_fim.split(':')[1])) if config.almoco_fim else None

        horarios_disponiveis = []
        
        # 4. Varre o dia de 30 em 30 minutos gerando os blocos possíveis
        while atual + duracao_servico <= limite:
            slot_inicio = atual
            slot_fim = atual + duracao_servico
            
            # Check 1: O horário conflita com o almoço?
            no_almoco = False
            if alm_ini and alm_fim:
                # Se o atendimento começar ou terminar dentro do intervalo de almoço
                if (slot_inicio >= alm_ini and slot_inicio < alm_fim) or (slot_fim > alm_ini and slot_fim <= alm_fim):
                    no_almoco = True
            
            # Check 2: O horário conflita com algum agendamento existente?
            conflito_agenda = False
            for agenda in agendamentos_dia:
                agend_ini = agenda.data_hora
                with app.app_context():
                    agend_fim = agenda.data_hora + timedelta(minutes=agenda.servico.duracao_minutos)
                
                # Regra de intersecção de intervalos (sobreposição de horários)
                if slot_inicio < agend_fim and slot_fim > agend_ini:
                    conflito_agenda = True
                    break
                    
            # Se passou em todas as validações, o horário está livre!
            if not no_almoco and not conflito_agenda:
                horarios_disponiveis.append(slot_inicio.strftime("%H:%M"))
                
            atual += timedelta(minutes=30) # Avança o ponteiro de tempo
            
        return horarios_disponiveis

def processar_mensagem(telefone_cliente, texto_recebido, manicure_id=1):
    """A inteligência principal que processa a entrada e define a saída."""
    
    if telefone_cliente not in sessoes_ativas:
        sessoes_ativas[telefone_cliente] = {"estado": 0, "servico_id": None, "data_foco": None, "mapa": {}}
        
    sessao = sessoes_ativas[telefone_cliente]
    texto = texto_recebido.strip()
    
    # ESTADO 0: Menu Principal
    if sessao["estado"] == 0:
        resposta, mapa = obter_mensagem_menu(manicure_id)
        sessao["mapa"] = mapa
        sessao["estado"] = 1
        return resposta
        
    # ESTADO 1: Escolhendo o Serviço e Conferindo Pacote
    elif sessao["estado"] == 1:
        if texto == "0":
            del sessoes_ativas[telefone_cliente]
            return "Ok! Vou te transferir. Aguarde um instante que a profissional já te responde."
            
        if texto in sessao["mapa"]:
            sessao["servico_id"] = sessao["mapa"][texto]
            
            with app.app_context():
                # Busca se a cliente já existe e tem pacote ativo ANTES de seguir
                cliente = Cliente.query.filter_by(manicure_id=manicure_id, whatsapp=telefone_cliente).first()
                pacote_ativo = None
                
                if cliente:
                    pacote_ativo = ClientePacote.query.filter_by(
                        cliente_id=cliente.id, 
                        ativo=True
                    ).filter(ClientePacote.sessoes_restantes > 0).first()
                
            if pacote_ativo:
                pacote_ativo.sessoes_restantes -= 1
                if pacote_ativo.sessoes_restantes == 0:
                    pacote_ativo.ativo = False
                db.session.add(pacote_ativo)
                mensagem_pagamento = f"\n🎁 *Pagamento:* Abatido do combo! Restam {pacote_ativo.sessoes_restantes} sessões."
                
                # Configurações para pacote ativo
                tipo_pg = 'Pacote'
                foi_pago = True
            else:
                servico_escolhido = Servico.query.get(sessao["servico_id"])
                valor_formatado = f"{servico_escolhido.valor:.2f}".replace('.', ',')
                mensagem_pagamento = f"\n💰 *Valor:* R$ {valor_formatado} (Pagamento no local)."
                
                # Configurações para avulso (pendente até ela comparecer)
                tipo_pg = 'Avulso'
                foi_pago = False
            
            # 3. Cria o agendamento final aplicando os novos parâmetros
            novo_agendamento = Agendamento(
                manicure_id=manicure_id,
                cliente_id=cliente.id,
                servico_id=sessao["servico_id"],
                data_hora=data_hora_final,
                status="Agendado", # Inicia apenas como agendado
                tipo_pagamento=tipo_pg,
                pago=foi_pago
            )
            db.session.add(novo_agendamento)
            db.session.commit()
        else:
            return "Opção inválida. Por favor, digite apenas o número correspondente ao serviço."

    # ESTADO 5: Decisão de Avulso ou Renovação
    elif sessao["estado"] == 5:
        if texto == "1":
            sessao["estado"] = 2
            return "Perfeito! Vamos seguir com o agendamento avulso.\n\nPara qual dia você gostaria? (Responda no formato DD/MM. Ex: 25/05)"
        elif texto == "2":
            del sessoes_ativas[telefone_cliente]
            return "Combinado! Vou te transferir agora mesmo. A profissional já te passa os valores dos combos novos."
        else:
            return "Opção inválida. Digite *1* para agendar avulso ou *2* para falar com a atendente."

    # ESTADO 2: Escolhendo a Data (Cálculo Dinâmico de Horários)
    elif sessao["estado"] == 2:
        try:
            dia, mes = map(int, texto.split('/'))
            ano = datetime.now().year
            data_buscada = datetime(ano, mes, dia)
            sessao["data_foco"] = data_buscada
            
            # Executa o algoritmo dinâmico
            horarios_livres = calcular_horarios_livres(manicure_id, data_buscada, sessao["servico_id"])
            
            if not horarios_livres:
                return f"Poxa, não tenho nenhum horário disponível para o dia {texto} ou não trabalhamos nesse dia. Pode tentar outra data?"
                
            # Monta o menu numérico de opções (1, 2, 3...) dinamicamente
            msg_horarios = f"Certo! No dia {texto}, tenho estes horários livres:\n\n"
            mapa_horarios = {}
            
            for index, hora_livre in enumerate(horarios_livres, start=1):
                msg_horarios += f"*{index}.* {hora_livre}\n"
                mapa_horarios[str(index)] = hora_livre
                
            msg_horarios += "\nQual número você prefere?"
            
            # Guarda o mapa de horários temporariamente na sessão do cliente
            sessao["mapa_horarios"] = mapa_horarios
            sessao["estado"] = 3
            return msg_horarios
        except Exception as e:
            return "Formato de data inválido. Use DD/MM. Exemplo: 25/05"
            
    # ESTADO 3: Concluindo o Agendamento e Baixando o Saldo Real
    elif sessao["estado"] == 3:
        # Recupera o mapa gerado dinamicamente no Estado 2
        mapa_horarios = sessao.get("mapa_horarios", {})
        
        if texto not in mapa_horarios:
            return f"Opção inválida. Escolha um número de 1 a {len(mapa_horarios)}."
            
        hora_str = mapa_horarios[texto] # Ex: "14:30"
        hora_int, minuto_int = map(int, hora_str.split(':'))
        
        data_hora_final = sessao["data_foco"].replace(hour=hora_int, minute=minuto_int, second=0, microsecond=0)
        
        with app.app_context():
            cliente = Cliente.query.filter_by(manicure_id=manicure_id, whatsapp=telefone_cliente).first()
            if not cliente:
                cliente = Cliente(manicure_id=manicure_id, nome=f"Cliente {telefone_cliente[-4:]}", whatsapp=telefone_cliente)
                db.session.add(cliente)
                db.session.commit()
            
            pacote_ativo = ClientePacote.query.filter_by(cliente_id=cliente.id, ativo=True).filter(ClientePacote.sessoes_restantes > 0).first()
            mensagem_pagamento = ""
            
            if pacote_ativo:
                pacote_ativo.sessoes_restantes -= 1
                if pacote_ativo.sessoes_restantes == 0:
                    pacote_ativo.ativo = False
                db.session.add(pacote_ativo)
                mensagem_pagamento = f"\n🎁 *Pagamento:* Abatido do combo! Restam {pacote_ativo.sessoes_restantes} sessões."
            else:
                servico_escolhido = Servico.query.get(sessao["servico_id"])
                valor_formatado = f"{servico_escolhido.valor:.2f}".replace('.', ',')
                mensagem_pagamento = f"\n💰 *Valor:* R$ {valor_formatado} (Pagamento no local)."
            
            novo_agendamento = Agendamento(
                manicure_id=manicure_id,
                cliente_id=cliente.id,
                servico_id=sessao["servico_id"],
                data_hora=data_hora_final,
                status="Confirmado"
            )
            db.session.add(novo_agendamento)
            db.session.commit()
            
        del sessoes_ativas[telefone_cliente] 
        return f"✅ Agendamento confirmado com sucesso para o dia {data_hora_final.strftime('%d/%m às %H:%M')}!{mensagem_pagamento}"
# ==========================================
# SIMULADOR DE TERMINAL
# ==========================================
if __name__ == "__main__":
    print("🤖 BOT INICIADO (Modo Terminal) - Digite 'sair' para encerrar")
    telefone_teste = "5547988881111"
    
    while True:
        entrada = input(f"\n[Cliente {telefone_teste}]: ")
        if entrada.lower() == 'sair':
            break
            
        resposta_bot = processar_mensagem(telefone_teste, entrada)
        print(f"[Bot]: {resposta_bot}")