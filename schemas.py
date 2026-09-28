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
    pass


class AtualizarStatusLeadPayload(BaseModel):
    campo: str
    marcar: bool = True


class SalvarObservacaoLeadPayload(BaseModel):
    observacoes: str
