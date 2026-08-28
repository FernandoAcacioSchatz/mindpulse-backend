"""
Modelos de validação de entrada (Pydantic). Toda rota que recebe
corpo de requisição usa um desses, em vez de aceitar `dict` solto
— isso garante formato, tipo e presença dos campos antes de
qualquer linha de lógica de negócio rodar.
"""
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class EncerrarPesquisaPayload(BaseModel):
    pesquisa_id: UUID
    ciclo_id: UUID


class RelatorioIARecord(BaseModel):
    ciclo_id: UUID
    prioridade: Optional[str] = None
    resumo_executivo: Optional[str] = None


class NotificarCriticoPayload(BaseModel):
    record: RelatorioIARecord


class LeadRecord(BaseModel):
    nome: Optional[str] = None
    email: Optional[str] = None
    empresa: Optional[str] = None
    mensagem: Optional[str] = None


class NotificarLeadPayload(BaseModel):
    record: LeadRecord


class ProvisionarEmpresaPayload(BaseModel):
    empresa_nome: str
    empresa_cnpj: Optional[str] = None
    rh_nome: str
    rh_email: str


class ExecutarJobResponse(BaseModel):
    """Usado só como referência de formato de resposta — não obrigatório usar."""
    pass
