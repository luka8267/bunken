alter table public.pdf_annotations
    add column if not exists drawing_data jsonb;

alter table public.pdf_annotations
    drop constraint if exists pdf_annotations_annotation_type_check;

alter table public.pdf_annotations
    add constraint pdf_annotations_annotation_type_check
    check (
        annotation_type in (
            'highlight',
            'page_note',
            'citation_note',
            'drawing'
        )
    );

alter table public.pdf_annotations
    drop constraint if exists pdf_annotations_drawing_data_check;

alter table public.pdf_annotations
    add constraint pdf_annotations_drawing_data_check
    check (
        drawing_data is null
        or jsonb_typeof(drawing_data) = 'object'
    );
