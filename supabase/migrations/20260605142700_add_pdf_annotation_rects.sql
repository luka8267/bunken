alter table public.pdf_annotations
    add column if not exists rect_x double precision,
    add column if not exists rect_y double precision,
    add column if not exists rect_width double precision,
    add column if not exists rect_height double precision;

alter table public.pdf_annotations
    drop constraint if exists pdf_annotations_rect_normalized_check;

alter table public.pdf_annotations
    add constraint pdf_annotations_rect_normalized_check
    check (
        (
            rect_x is null
            and rect_y is null
            and rect_width is null
            and rect_height is null
        )
        or (
            rect_x >= 0
            and rect_x <= 1
            and rect_y >= 0
            and rect_y <= 1
            and rect_width > 0
            and rect_width <= 1
            and rect_height > 0
            and rect_height <= 1
            and rect_x + rect_width <= 1
            and rect_y + rect_height <= 1
        )
    );

create index if not exists pdf_annotations_user_paper_rect_idx
    on public.pdf_annotations (user_id, paper_id, page_number)
    where rect_x is not null;
